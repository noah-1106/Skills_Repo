"""Versioned intervention briefs, content assets and immutable channel publications."""
from __future__ import annotations

import hashlib
from datetime import datetime
from urllib.parse import urlparse

from fastapi import HTTPException

from ..db import all_rows, dumps, loads, one, utc_now
from ..security import audit
from .state import scoped_object, transition


def _hash(value) -> str:
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def _observation_hash(row: dict) -> str:
    return _hash({key: row.get(key) for key in (
        "id", "answer_id", "brand_entity_id", "revision", "entity_status", "mentioned", "depth",
        "sentiment", "top_choice", "evidence", "citation_urls_json", "judge_status", "review_status",
    )})


def observation_hash(row: dict) -> str:
    return _observation_hash(row)


def _brief_values(payload: dict) -> dict:
    return {
        "information_gain": payload.get("information_gain", "").strip(),
        "hypothesis": payload.get("hypothesis", "").strip(),
        "expected_observation": payload.get("expected_observation", "").strip(),
        "channels": payload.get("channels") or [],
        "success_criteria": payload.get("success_criteria", "").strip(),
        "claims": payload.get("claims") or [],
    }


def _asset_values(payload: dict) -> dict:
    return {
        "title": payload.get("title", "").strip(),
        "asset_type": payload.get("asset_type", "fact_page"),
        "content": payload.get("content") or {},
        "facts": payload.get("facts") or [],
        "applicability": payload.get("applicability", "").strip(),
        "exclusions": payload.get("exclusions", "").strip(),
    }


def _validate_claims(conn, action: dict, claims: list[dict]) -> list[dict]:
    if not isinstance(claims, list):
        raise HTTPException(400, "主张必须是数组")
    opportunity = one(conn, "SELECT * FROM opportunities WHERE id=?", (action["opportunity_id"],))
    evidence = loads(opportunity["evidence_json"], {})
    allowed_answers = {int(value) for value in evidence.get("answer_ids", [])}
    normalized = []
    for claim in claims:
        text = str(claim.get("text", "")).strip()
        status = claim.get("status")
        refs = claim.get("evidence_refs") or []
        if not text or status not in ("evidence_linked", "pending") or not isinstance(refs, list):
            raise HTTPException(400, "每条主张必须包含 text、有效状态和 evidence_refs 数组")
        if status == "evidence_linked" and not refs:
            raise HTTPException(400, "有证据主张至少需要一个 evidence_ref；否则必须标为 pending")
        checked = []
        for ref in refs:
            try:
                answer_id = int(ref.get("answer_id"))
            except (TypeError, ValueError) as error:
                raise HTTPException(400, "evidence_ref 必须包含 answer_id") from error
            answer = one(conn, "SELECT * FROM answers WHERE id=? AND project_id=? AND client_id=?",
                         (answer_id, action["project_id"], action["client_id"]))
            if not answer or answer_id not in allowed_answers:
                raise HTTPException(400, "evidence_ref 必须属于该 Opportunity 的基线证据范围")
            item = {"answer_id": answer_id, "answer_hash": answer.get("raw_text_sha256") or ""}
            if ref.get("answer_hash") and ref["answer_hash"] != item["answer_hash"]:
                raise HTTPException(400, "Answer hash 与证据记录不匹配")
            if ref.get("observation_id") is not None:
                observation = one(conn, "SELECT * FROM observations WHERE id=? AND answer_id=?",
                                  (int(ref["observation_id"]), answer_id))
                if not observation:
                    raise HTTPException(400, "Observation 不属于引用的 Answer")
                revision = int(ref.get("revision") or observation["revision"])
                if revision != observation["revision"]:
                    raise HTTPException(400, "Observation revision 与证据记录不匹配")
                digest = _observation_hash(observation)
                if ref.get("hash") and ref["hash"] != digest:
                    raise HTTPException(400, "Observation hash 与证据记录不匹配")
                item.update({"observation_id": observation["id"], "revision": revision, "hash": digest})
            if ref.get("citation_id") is not None:
                citation = one(conn, "SELECT * FROM citations WHERE id=? AND answer_id=?",
                               (int(ref["citation_id"]), answer_id))
                if not citation:
                    raise HTTPException(400, "Citation 不属于引用的 Answer")
                if item.get("observation_id") and citation.get("observation_id") not in (None, item["observation_id"]):
                    raise HTTPException(400, "Citation 与 Observation 的父子关系不匹配")
                if ref.get("citation_hash") and ref["citation_hash"] != citation["content_hash"]:
                    raise HTTPException(400, "Citation hash 与证据记录不匹配")
                item.update({"citation_id": citation["id"], "citation_hash": citation["content_hash"]})
            checked.append(item)
        normalized.append({"text": text, "status": status, "evidence_refs": checked})
    return normalized


def _default_claims(conn, action: dict) -> list[dict]:
    opportunity = one(conn, "SELECT * FROM opportunities WHERE id=?", (action["opportunity_id"],))
    evidence = loads(opportunity["evidence_json"], {})
    refs = []
    for answer_id in evidence.get("answer_ids", [])[:3]:
        observation = one(conn, """SELECT * FROM observations WHERE answer_id=? AND entity_status='confirmed'
            ORDER BY CASE WHEN depth='recommended' THEN 0 ELSE 1 END,revision DESC,id LIMIT 1""", (answer_id,))
        ref = {"answer_id": int(answer_id)}
        if observation:
            ref.update({"observation_id": observation["id"], "revision": observation["revision"],
                        "hash": _observation_hash(observation)})
        refs.append(ref)
    return [{"text": f"基线样本显示该问题存在{opportunity['gap_type']}，内容需要补充可核验事实与适用边界。",
             "status": "evidence_linked" if refs else "pending", "evidence_refs": refs}]


def initialize_action(conn, action: dict, actor: int) -> None:
    opportunity = one(conn, "SELECT * FROM opportunities WHERE id=?", (action["opportunity_id"],))
    now = utc_now()
    claims = _validate_claims(conn, action, _default_claims(conn, action))
    values = {
        "information_gain": "补充适用于该问题的品牌事实、来源和不适用边界",
        "hypothesis": "增加可核验信息后，后续同口径样本可能出现变化；不预设策略因果。",
        "expected_observation": "在 D7/D14/D28 观察主品牌覆盖、推荐或负面风险的同口径变化",
        "channels": [],
        "success_criteria": "固定基线与目标正式 Run；严格同口径且样本充分时观察对应指标方向",
        "claims": claims,
    }
    brief_id = conn.execute("""INSERT INTO content_briefs(client_id,project_id,action_id,version,target_prompt_item_id,
        information_gain,hypothesis,expected_observation,channels_json,success_criteria,claims_json,content_hash,created_by,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (action["client_id"], action["project_id"], action["id"], 1, opportunity["prompt_item_id"],
         values["information_gain"], values["hypothesis"], values["expected_observation"], dumps(values["channels"]),
         values["success_criteria"], dumps(claims), _hash(values), actor, now)).lastrowid
    asset = {"title": action["title"], "asset_type": "fact_page",
             "content": {"target_url": action.get("target_url") or "", "summary": ""},
             "facts": claims, "applicability": "", "exclusions": ""}
    conn.execute("""INSERT INTO action_assets(client_id,project_id,action_id,brief_id,title,asset_type,version,
        content_json,facts_json,content_hash,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (action["client_id"], action["project_id"], action["id"], brief_id, asset["title"], asset["asset_type"], 1,
         dumps(asset["content"]), dumps(claims), _hash(asset), actor, now))


def brief_public(row: dict, internal: bool = True) -> dict:
    result = dict(row)
    for field in ("channels", "claims"):
        result[field] = loads(result.pop(f"{field}_json"), [])
    if not internal:
        for claim in result["claims"]:
            claim["evidence_count"] = len(claim.get("evidence_refs", []))
            claim.pop("evidence_refs", None)
        result.pop("content_hash", None)
    return result


def asset_public(row: dict, internal: bool = True) -> dict:
    result = dict(row)
    result["content"] = loads(result.pop("content_json"), {})
    result["facts"] = loads(result.pop("facts_json"), [])
    if not internal:
        for fact in result["facts"]:
            fact["evidence_count"] = len(fact.get("evidence_refs", []))
            fact.pop("evidence_refs", None)
        result.pop("content_hash", None)
    return result


def publication_public(row: dict, internal: bool = True) -> dict:
    result = dict(row)
    if not internal:
        result.pop("cost", None)
        result.pop("currency", None)
        result.pop("notes", None)
    return result


def create_brief(conn, action: dict, actor: int, payload: dict) -> dict:
    if action["status"] in ("verified", "not_effective", "stopped"):
        raise HTTPException(409, "已结束的 cohort 不可修改；请创建后续 Action")
    values = _brief_values(payload)
    values["claims"] = _validate_claims(conn, action, values["claims"])
    version = (one(conn, "SELECT MAX(version) AS value FROM content_briefs WHERE action_id=?", (action["id"],))["value"] or 0) + 1
    now = utc_now()
    brief_id = conn.execute("""INSERT INTO content_briefs(client_id,project_id,action_id,version,target_prompt_item_id,
        information_gain,hypothesis,expected_observation,channels_json,success_criteria,claims_json,content_hash,created_by,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (action["client_id"], action["project_id"], action["id"], version,
         one(conn, "SELECT prompt_item_id FROM opportunities WHERE id=?", (action["opportunity_id"],))["prompt_item_id"],
         values["information_gain"], values["hypothesis"], values["expected_observation"], dumps(values["channels"]),
         values["success_criteria"], dumps(values["claims"]), _hash(values), actor, now)).lastrowid
    row = one(conn, "SELECT * FROM content_briefs WHERE id=?", (brief_id,))
    audit(conn, actor, action, "content_brief", row["id"], "create", None, row)
    return brief_public(row)


def update_brief(conn, brief: dict, actor: int, payload: dict) -> dict:
    if brief["status"] != "draft":
        raise HTTPException(409, "已审批或历史 Brief 不可覆盖，请创建新版本")
    action = one(conn, "SELECT * FROM actions WHERE id=?", (brief["action_id"],))
    values = _brief_values(payload)
    values["claims"] = _validate_claims(conn, action, values["claims"])
    conn.execute("""UPDATE content_briefs SET information_gain=?,hypothesis=?,expected_observation=?,channels_json=?,
        success_criteria=?,claims_json=?,content_hash=? WHERE id=?""",
        (values["information_gain"], values["hypothesis"], values["expected_observation"], dumps(values["channels"]),
         values["success_criteria"], dumps(values["claims"]), _hash(values), brief["id"]))
    row = one(conn, "SELECT * FROM content_briefs WHERE id=?", (brief["id"],))
    audit(conn, actor, action, "content_brief", brief["id"], "update", brief, row)
    return brief_public(row)


def approve_brief(conn, brief: dict, actor: int) -> dict:
    if brief["status"] == "approved":
        return brief_public(brief)
    if brief["status"] != "draft":
        raise HTTPException(409, "legacy Brief 没有结构化证据，请创建新版本")
    values = _brief_values(brief_public(brief))
    if not all(values[key] for key in ("information_gain", "hypothesis", "expected_observation", "success_criteria")):
        raise HTTPException(409, "Brief 的信息增量、假设、预期观察和成功标准必须完整")
    if not values["claims"] or any(claim["status"] != "evidence_linked" for claim in values["claims"]):
        raise HTTPException(409, "Brief 仍有待确认主张，不能审批")
    conn.execute("UPDATE content_briefs SET status='superseded' WHERE action_id=? AND status='approved'", (brief["action_id"],))
    conn.execute("UPDATE content_briefs SET status='approved',approved_by=?,approved_at=? WHERE id=?",
                 (actor, utc_now(), brief["id"]))
    row = one(conn, "SELECT * FROM content_briefs WHERE id=?", (brief["id"],))
    action = one(conn, "SELECT * FROM actions WHERE id=?", (brief["action_id"],))
    audit(conn, actor, action, "content_brief", brief["id"], "approve", brief, row)
    return brief_public(row)


def create_asset(conn, action: dict, actor: int, payload: dict) -> dict:
    if action["status"] in ("verified", "not_effective", "stopped"):
        raise HTTPException(409, "已结束的 cohort 不可新增资产；请创建后续 Action")
    values = _asset_values(payload)
    if not values["title"]:
        raise HTTPException(400, "Asset 标题不能为空")
    values["facts"] = _validate_claims(conn, action, values["facts"])
    brief = scoped_object(conn, "content_briefs", int(payload["brief_id"]), action)
    supersedes = None
    version = 1
    if payload.get("supersedes_asset_id"):
        supersedes = scoped_object(conn, "action_assets", int(payload["supersedes_asset_id"]), action)
        version = supersedes["version"] + 1
        values["title"] = values["title"] or supersedes["title"]
    now = utc_now()
    asset_id = conn.execute("""INSERT INTO action_assets(client_id,project_id,action_id,brief_id,title,asset_type,version,
        content_json,facts_json,applicability,exclusions,supersedes_asset_id,content_hash,created_by,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (action["client_id"], action["project_id"], action["id"], brief["id"], values["title"], values["asset_type"],
         version, dumps(values["content"]), dumps(values["facts"]), values["applicability"], values["exclusions"],
         supersedes["id"] if supersedes else None, _hash(values), actor, now)).lastrowid
    row = one(conn, "SELECT * FROM action_assets WHERE id=?", (asset_id,))
    audit(conn, actor, action, "action_asset", asset_id, "create", None, row)
    return asset_public(row)


def update_asset(conn, asset: dict, actor: int, payload: dict) -> dict:
    if asset["status"] != "draft":
        raise HTTPException(409, "已审批或历史 Asset 不可覆盖，请创建新版本")
    action = one(conn, "SELECT * FROM actions WHERE id=?", (asset["action_id"],))
    values = _asset_values(payload)
    values["facts"] = _validate_claims(conn, action, values["facts"])
    conn.execute("""UPDATE action_assets SET title=?,asset_type=?,content_json=?,facts_json=?,applicability=?,exclusions=?,
        content_hash=? WHERE id=?""", (values["title"], values["asset_type"], dumps(values["content"]), dumps(values["facts"]),
        values["applicability"], values["exclusions"], _hash(values), asset["id"]))
    row = one(conn, "SELECT * FROM action_assets WHERE id=?", (asset["id"],))
    audit(conn, actor, action, "action_asset", asset["id"], "update", asset, row)
    return asset_public(row)


def approve_asset(conn, asset: dict, actor: int) -> dict:
    if asset["status"] == "approved":
        return asset_public(asset)
    if asset["status"] != "draft":
        raise HTTPException(409, "legacy Asset 没有结构化事实，请创建新版本")
    brief = one(conn, "SELECT * FROM content_briefs WHERE id=?", (asset["brief_id"],))
    if not brief or brief["status"] != "approved":
        raise HTTPException(409, "Asset 引用的 Brief 必须先审批")
    facts = loads(asset["facts_json"], [])
    if not facts or any(fact["status"] != "evidence_linked" for fact in facts):
        raise HTTPException(409, "Asset 仍有待确认事实，不能审批或发布")
    if asset["supersedes_asset_id"]:
        conn.execute("UPDATE action_assets SET status='superseded' WHERE id=?", (asset["supersedes_asset_id"],))
    conn.execute("UPDATE action_assets SET status='approved',approved_by=?,approved_at=? WHERE id=?",
                 (actor, utc_now(), asset["id"]))
    row = one(conn, "SELECT * FROM action_assets WHERE id=?", (asset["id"],))
    action = one(conn, "SELECT * FROM actions WHERE id=?", (asset["action_id"],))
    audit(conn, actor, action, "action_asset", asset["id"], "approve", asset, row)
    return asset_public(row)


def validate_action_package(conn, action: dict) -> None:
    brief = one(conn, "SELECT * FROM content_briefs WHERE action_id=? ORDER BY version DESC LIMIT 1", (action["id"],))
    assets = all_rows(conn, "SELECT * FROM action_assets WHERE action_id=? AND status='draft'", (action["id"],))
    if not brief or brief["status"] == "legacy" or not assets and not one(conn, "SELECT id FROM action_assets WHERE action_id=?", (action["id"],)):
        raise HTTPException(409, "提交审核前需要结构化 Brief 和至少一个 Asset")


def approve_action_package(conn, action: dict, actor: int) -> None:
    brief = one(conn, "SELECT * FROM content_briefs WHERE action_id=? ORDER BY version DESC LIMIT 1", (action["id"],))
    if not brief:
        raise HTTPException(409, "缺少 Brief")
    approve_brief(conn, brief, actor)
    assets = all_rows(conn, "SELECT * FROM action_assets WHERE action_id=? AND status='draft' ORDER BY id", (action["id"],))
    if not assets and not one(conn, "SELECT id FROM action_assets WHERE action_id=? AND status='approved'", (action["id"],)):
        raise HTTPException(409, "批准 Action 前至少需要一个 Asset")
    for asset in assets:
        approve_asset(conn, asset, actor)


def _publication_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as error:
        raise HTTPException(400, "发布时间必须是有效 ISO 时间") from error
    if not parsed.tzinfo:
        raise HTTPException(400, "发布时间必须包含时区")
    return value


def _http_url(value: str) -> str:
    parsed = urlparse(value or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "发布 URL 必须是有效的 HTTP(S) 地址")
    return value


def record_publication(conn, action: dict, actor: int, payload: dict) -> dict:
    if action["status"] not in ("approved", "published", "remeasure_due"):
        raise HTTPException(409, "只有已批准且未结束的 cohort 可以登记发布")
    asset = scoped_object(conn, "action_assets", int(payload["asset_id"]), action)
    if asset["status"] != "approved":
        raise HTTPException(409, "只有结构化事实已审批的 Asset 可以发布")
    published_at = _publication_time(payload.get("published_at"))
    url = _http_url(payload.get("url"))
    cost = payload.get("cost")
    currency = (payload.get("currency") or "").strip().upper()
    if cost is not None and not currency:
        raise HTTPException(400, "填写成本时必须填写币种；未知成本请留空，不能记为 0")
    now = utc_now()
    publication_id = conn.execute("""INSERT INTO asset_publications(client_id,project_id,action_id,asset_id,channel,outlet,url,
        published_at,cost,currency,relationship,notes,recorded_by,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (action["client_id"], action["project_id"], action["id"], asset["id"], payload["channel"].strip(),
         (payload.get("outlet") or "").strip(), url, published_at, cost, currency,
         payload.get("relationship") or "unknown", payload.get("notes") or "", actor, now)).lastrowid
    row = one(conn, "SELECT * FROM asset_publications WHERE id=?", (publication_id,))
    event_id = conn.execute("""INSERT INTO external_events(client_id,project_id,event_at,kind,description,source,created_by,created_at,
        action_id,asset_id,publication_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (action["client_id"], action["project_id"], published_at, "内容发布", f"第 {action['geo_step']} 步：{action['title']}",
         url, actor, now, action["id"], asset["id"], publication_id)).lastrowid
    first = one(conn, "SELECT COUNT(*) AS count FROM asset_publications WHERE action_id=?", (action["id"],))["count"] == 1
    if first:
        extra = {"published_at": published_at, "published_url": url,
                 "artifact_version": payload.get("artifact_version") or f"v{asset['version']}"}
        if action["status"] == "approved":
            transition(conn, "actions", action, "published", actor, "登记首条真实渠道发布", extra)
        else:
            conn.execute("UPDATE actions SET published_at=?,published_url=?,artifact_version=?,updated_at=? WHERE id=?",
                         (*extra.values(), now, action["id"]))
    audit(conn, actor, action, "asset_publication", publication_id, "publish", None,
          {**row, "external_event_id": event_id})
    return publication_public(row)


def publish_legacy(conn, action: dict, actor: int, payload: dict) -> dict:
    asset = one(conn, "SELECT * FROM action_assets WHERE action_id=? AND status='approved' ORDER BY version DESC,id DESC LIMIT 1",
                (action["id"],))
    if not asset:
        raise HTTPException(409, "旧发布接口也需要已审批 Brief 与 Asset")
    return record_publication(conn, action, actor, {
        "asset_id": asset["id"], "channel": "legacy", "outlet": "", "url": payload.get("published_url"),
        "published_at": payload.get("published_at"), "artifact_version": payload.get("artifact_version"),
        "relationship": "unknown", "cost": None,
    })


def round_public(row: dict, internal: bool = True) -> dict:
    result = dict(row)
    if "comparison_json" in result:
        result["comparison"] = loads(result.pop("comparison_json"), {})
    else:
        result["comparison"] = result.get("comparison") or {}
    if "evidence_refs_json" in result:
        result["evidence_refs"] = loads(result.pop("evidence_refs_json"), [])
    else:
        result["evidence_refs"] = result.get("evidence_refs") or []
    if not internal:
        result["evidence_count"] = len(result.pop("evidence_refs"))
        result.pop("comparison_hash", None)
        comparison = result.get("comparison") or {}
        result["comparison"] = {key: value for key, value in comparison.items()
                                if key in ("comparable", "reason", "pair_completeness", "sample_completeness", "delta", "interpretation")}
    return result


def decision_summary(action: dict, briefs: list[dict], assets: list[dict], publications: list[dict], rounds: list[dict],
                     opportunity: dict) -> dict:
    approved_brief = next((item for item in briefs if item["status"] == "approved"), None)
    approved_assets = [item for item in assets if item["status"] == "approved"]
    assessed = [item for item in rounds if item["status"] in ("measured", "insufficient_evidence", "incomparable")]
    latest = assessed[-1] if assessed else None
    if not approved_brief or not approved_assets:
        next_step = "完成并审批 Brief 与至少一个内容资产"
    elif not publications:
        next_step = "登记第一条真实渠道发布"
    elif not rounds:
        next_step = "为同一 cohort 安排 D7/D14/D28 复测"
    elif any(item["status"] == "pending_measurement" for item in rounds):
        pending = next(item for item in rounds if item["status"] == "pending_measurement")
        next_step = ("前往测量页显式执行 Consumer Web 复测；系统不会自动发送网页问题"
                     if pending["surface"] == "consumer_web" else "等待 Provider 调度创建 Run，再由管理员指定正式 Run 并评估")
    elif latest and latest["status"] == "insufficient_evidence":
        next_step = "补充同口径有效样本后创建新的复测轮次"
    elif latest and latest["status"] == "incomparable":
        next_step = "按基线冻结协议创建可比 Wave，再安排新一轮复测"
    elif latest and latest["observed_change"] == "improved":
        next_step = "保留当前 cohort 记录，按下一计划节点继续观察"
    elif latest:
        next_step = "复核内容与渠道事实，另建后续 Action，不重写本轮证据"
    else:
        next_step = "检查复测节点与正式 Run"
    return {
        "key_questions": [{"prompt_item_id": opportunity["prompt_item_id"], "prompt_text": opportunity.get("prompt_text") or "",
                           "gap_type": opportunity["gap_type"]}],
        "changes": {"assets": [{"id": item["id"], "title": item["title"], "version": item["version"]} for item in approved_assets],
                    "publications": [{"id": item["id"], "asset_id": item["asset_id"], "channel": item["channel"],
                                      "outlet": item["outlet"], "url": item["url"], "published_at": item["published_at"]}
                                     for item in publications]},
        "observations": [{"round_id": item["id"], "offset_days": item["offset_days"], "status": item["status"],
                          "observed_change": item["observed_change"] or "unknown", "attribution_status": item["attribution_status"],
                          "evidence_strength": ("严格同口径且达到样本阈值" if item["status"] == "measured" else
                                                "样本或完整度不足" if item["status"] == "insufficient_evidence" else
                                                "测量口径不可比" if item["status"] == "incomparable" else
                                                "尚未测量" if item["status"] == "pending_measurement" else "历史证据不可用")}
                         for item in rounds],
        "next_recommendation": next_step,
        "causal_boundary": "同一 cohort 的同期变化不等于任何单篇内容或 GEO Action 的因果效果。",
    }


def _mark_refs_available(conn, refs: list[dict]) -> None:
    for ref in refs:
        answer = one(conn, "SELECT content_retained,raw_text_sha256 FROM answers WHERE id=?", (ref.get("answer_id"),))
        available = bool(answer)
        reason = "" if answer else "answer_missing"
        if answer and not answer.get("content_retained", 1):
            available, reason = False, "raw_purged"
        expected_hash = ref.get("answer_hash") or (ref.get("hash") if ref.get("kind") == "answer" else "")
        if answer and expected_hash and expected_hash != (answer.get("raw_text_sha256") or ""):
            available, reason = False, "answer_hash_changed"
        ref["available_now"] = available
        if reason:
            ref["unavailable_reason"] = reason


def intervention_detail(conn, action: dict, role: str = "admin") -> dict:
    internal = role in ("admin", "analyst")
    opportunity = one(conn, """SELECT o.*,p.text AS prompt_text FROM opportunities o
        JOIN prompt_items p ON p.id=o.prompt_item_id WHERE o.id=?""", (action["opportunity_id"],))
    if not internal:
        evidence = loads(opportunity.pop("evidence_json"), {})
        opportunity.pop("score_json", None)
        opportunity["evidence"] = {"answer_ids": evidence.get("answer_ids", []),
                                   "evidence_count": len(evidence.get("evidence", []))}
    briefs = [brief_public(row, internal) for row in all_rows(conn,
        "SELECT * FROM content_briefs WHERE action_id=? ORDER BY version DESC", (action["id"],))]
    assets = [asset_public(row, internal) for row in all_rows(conn,
        "SELECT * FROM action_assets WHERE action_id=? ORDER BY id DESC", (action["id"],))]
    publications = [publication_public(row, internal) for row in all_rows(conn,
        "SELECT * FROM asset_publications WHERE action_id=? ORDER BY published_at,id", (action["id"],))]
    rounds = [round_public(row, internal) for row in all_rows(conn,
        "SELECT * FROM action_remeasurement_rounds WHERE action_id=? ORDER BY round_no", (action["id"],))]
    for item in rounds:
        item["schedule"] = one(conn, "SELECT id,status,scheduled_at,last_run_id,last_error FROM schedules WHERE remeasurement_round_id=?",
                               (item["id"],))
    if internal:
        for brief in briefs:
            for claim in brief["claims"]:
                _mark_refs_available(conn, claim.get("evidence_refs", []))
        for asset in assets:
            for fact in asset["facts"]:
                _mark_refs_available(conn, fact.get("evidence_refs", []))
        for item in rounds:
            _mark_refs_available(conn, item["evidence_refs"])
    events = all_rows(conn, "SELECT * FROM external_events WHERE action_id=? ORDER BY event_at,id", (action["id"],))
    timeline = [{"event_at": row["event_at"], "kind": row["kind"], "description": row["description"],
                 "source": row["source"], "event_id": row["id"], "publication_id": row.get("publication_id"),
                 "remeasurement_round_id": row.get("remeasurement_round_id")} for row in events]
    for brief in briefs:
        if brief.get("approved_at"):
            timeline.append({"event_at": brief["approved_at"], "kind": "brief_approved",
                             "description": f"Brief v{brief['version']} 已审批", "object_id": brief["id"]})
    for asset in assets:
        if asset.get("approved_at"):
            timeline.append({"event_at": asset["approved_at"], "kind": "asset_approved",
                             "description": f"Asset {asset['title']} v{asset['version']} 已审批", "object_id": asset["id"]})
    timeline.sort(key=lambda item: (item["event_at"], item.get("event_id") or 0, item["kind"]))
    summary = decision_summary(action, briefs, assets, publications, rounds, opportunity)
    return {"action": action, "opportunity": opportunity, "briefs": briefs, "assets": assets,
            "publications": publications, "rounds": rounds, "timeline": timeline,
            "decision_summary": summary, "next_recommendation": summary["next_recommendation"],
            "causal_boundary": summary["causal_boundary"]}
