"""Wave/run creation, persistent execution and evidence loading."""
from __future__ import annotations

import hashlib
import math
import threading
import time
import urllib.parse
from collections import Counter
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException

from .. import config
from ..db import all_rows, connect, dumps, loads, one, transaction, utc_now
from ..engine.judge import JUDGE_VERSION, fallback_observations, judge_answer
from ..providers import ProviderError, build_provider
from ..security import SecretStore, audit
from .budgets import authorize_budget, release as release_budget, reserve
from .costs import estimate_wave as estimate_wave_cost
from .costs import frozen_engines, record_attempt, rule_for
from .execution import (answer_execution_for, execution_maps, judge_execution_for,
                        legacy_execution_fields)
from .state import logical_id

VALID_SAMPLE_DEFINITION = "succeeded_nonempty_v1"
_ENGINE_LOCKS: dict[int, threading.Lock] = {}
_ENGINE_LOCKS_GUARD = threading.Lock()
_LAST_CALL: dict[int, float] = {}


@contextmanager
def _engine_slot(engine: dict):
    """Serialize each engine and apply its configured requests/second limit."""
    with _ENGINE_LOCKS_GUARD:
        lock = _ENGINE_LOCKS.setdefault(int(engine["id"]), threading.Lock())
    with lock:
        interval = 1 / max(0.1, float(engine.get("rate_limit") or 12))
        wait = interval - (time.monotonic() - _LAST_CALL.get(int(engine["id"]), 0.0))
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[int(engine["id"])] = time.monotonic()
        yield


def engine_public(row: dict, include_internal: bool = False) -> dict:
    result = dict(row)
    result.pop("secret_ref", None)
    rule = loads(result.pop("cost_rule_json", "{}"), {})
    if include_internal:
        result["cost_rule"] = rule
    else:
        result.pop("cost_rule", None)
    for key in ("capabilities", "answer_defaults", "judge_defaults", "health_defaults"):
        result[key] = loads(result.pop(f"{key}_json", "{}"), {})
    result["has_api_key"] = bool(row.get("secret_ref"))
    return result


def engine_execution(row: dict) -> dict:
    result = dict(row)
    result["cost_rule"] = rule_for(row)
    return result


def entity_public(row: dict) -> dict:
    result = dict(row)
    result["entity_card"] = loads(result.pop("entity_card_json", "{}"), {})
    return result


def prompt_set_content(conn, prompt_set_id: int) -> list[dict]:
    rows = all_rows(conn, "SELECT * FROM prompt_items WHERE prompt_set_id=? ORDER BY id", (prompt_set_id,))
    for row in rows:
        row["fields"] = loads(row.pop("fields_json"), {})
    return rows


def create_wave(project: dict, actor: int, payload: dict) -> dict:
    with transaction() as conn:
        prompt_set = one(conn, "SELECT * FROM prompt_sets WHERE id=? AND project_id=? AND client_id=?",
                         (payload["prompt_set_id"], project["id"], project["client_id"]))
        if not prompt_set or prompt_set["status"] != "frozen":
            raise HTTPException(409, "请先审核并冻结问题集")
        items = prompt_set_content(conn, prompt_set["id"])
        if not items:
            raise HTTPException(409, "冻结问题集没有题目")
        engine_ids = sorted(set(int(value) for value in payload["engine_ids"]))
        engines = [one(conn, "SELECT * FROM engine_configs WHERE id=? AND project_id=? AND client_id=? AND enabled=1",
                       (engine_id, project["id"], project["client_id"])) for engine_id in engine_ids]
        if not engines or any(engine is None for engine in engines):
            raise HTTPException(400, "至少选择一个当前项目已启用的引擎")
        modes = {engine["mode"] for engine in engines}
        targets = {engine["measurement_target"] for engine in engines}
        if len(modes) != 1 or len(targets) != 1:
            raise HTTPException(409, "同一 wave 不能混合 memory/search 或 API/产品端口径")
        manual_web = targets == {"consumer_web"} and len(engines) == 1 and engines[0]["kind"] == "manual_web"
        if targets == {"consumer_web"} and not manual_web:
            raise HTTPException(409, "Consumer Web Wave 只能选择一个 manual_web 目标，不能与 Provider 或其他目标混合")
        if not manual_web and payload.get("collection_protocol"):
            raise HTTPException(400, "采集协议仅用于人工 Consumer Web Wave")
        use_judge = bool(payload.get("use_judge", True))
        if not use_judge and (payload.get("judge_engine_id") or payload.get("judge_overrides")):
            raise HTTPException(409, "关闭 Judge 时不能配置 Judge 引擎或参数")
        if manual_web and payload.get("answer_overrides"):
            raise HTTPException(400, "人工 Web 没有 Provider 回答参数；请只配置独立 Judge")
        selected_override_ids = {int(value) for value in (payload.get("answer_overrides") or {})}
        if not selected_override_ids <= set(engine_ids):
            raise HTTPException(400, "answer_overrides 包含未选中的回答引擎")
        collection_protocol = None
        judge_engine = None
        judge_signature = None
        if manual_web:
            collection_protocol = dict(payload.get("collection_protocol") or {})
            product_url = str(collection_protocol.get("product_url") or "").rstrip("/")
            if not collection_protocol or product_url != engines[0]["base_url"].rstrip("/"):
                raise HTTPException(409, "冻结采集协议必须使用目标配置中的产品入口")
            collection_protocol["product_url"] = engines[0]["base_url"].rstrip("/")
            if bool(collection_protocol.get("networking")) != (engines[0]["mode"] == "search"):
                raise HTTPException(409, "采集协议的联网声明必须与人工目标的 memory/search 口径一致")
            if use_judge and not payload.get("judge_engine_id"):
                raise HTTPException(409, "人工 Web 默认全量 Judge，必须选择一个独立 Provider Judge 引擎")
        if use_judge and payload.get("judge_engine_id"):
            judge_engine = one(conn, "SELECT * FROM engine_configs WHERE id=? AND project_id=? AND client_id=? AND enabled=1 AND kind!='manual_web'",
                               (payload.get("judge_engine_id"), project["id"], project["client_id"]))
            if not judge_engine:
                raise HTTPException(409, "必须选择当前项目已启用的独立 Provider Judge 引擎")
            if not manual_web and int(judge_engine["id"]) in engine_ids:
                raise HTTPException(409, "独立 Judge 不能同时是本次回答引擎；同引擎判定请留空 Judge 选择")
            if not manual_web and (judge_engine["kind"] == "demo") != all(engine["kind"] == "demo" for engine in engines):
                raise HTTPException(409, "Provider 回答与 Judge 不能混用 Demo 和真实引擎；请使用同类型隔离配置")
            judge_signature = {"id": judge_engine["id"], "name": judge_engine["name"],
                               "kind": judge_engine["kind"], "model": judge_engine["model"],
                               "mode": judge_engine["mode"], "measurement_target": judge_engine["measurement_target"],
                               "role": "independent_judge"}
        entities = [entity_public(row) for row in all_rows(
            conn, "SELECT * FROM brand_entities WHERE project_id=? AND client_id=? AND status='confirmed' AND role IN ('primary','competitor') AND valid_to IS NULL ORDER BY role,name",
            (project["id"], project["client_id"]))]
        if not any(entity["role"] == "primary" for entity in entities):
            raise HTTPException(409, "需要管理员先确认一个主品牌实体")
        entity_ids = [entity["id"] for entity in entities]
        entity_version = hashlib.sha256(dumps([{key: value for key, value in entity.items() if key != "reviewed_by"}
                                                for entity in entities]).encode()).hexdigest()
        competitor_pool_hash = hashlib.sha256(dumps(sorted(
            entity["id"] for entity in entities if entity["role"] == "competitor")).encode()).hexdigest()
        settings = {**config.DEFAULT_PROJECT_SETTINGS, **loads(project["settings_json"], {})}
        stats = {**settings, **(payload.get("stats") or {})}
        repeats = int(payload.get("repeats") or stats.get("repeats", 3))
        if repeats < 1 or repeats > 5:
            raise HTTPException(400, "采样轮数必须在 1–5 之间")
        if not 0.5 <= float(stats.get("min_pair_completeness", 0.9)) <= 1:
            raise HTTPException(400, "配对完整度阈值必须在 50%–100% 之间")
        engine_signature = [{"id": engine["id"], "name": engine["name"], "kind": engine["kind"],
                             "model": engine["model"], "mode": engine["mode"],
                             "measurement_target": engine["measurement_target"]} for engine in engines]
        answer_map, judge_map = execution_maps(engines, judge_engine, {**payload, "use_judge": use_judge},
                                                manual_web=manual_web)
        legacy_fields = legacy_execution_fields(answer_map, judge_map, manual_web=manual_web)
        protocol = {
            "prompt_set_id": prompt_set["id"], "prompt_set_hash": prompt_set["content_hash"],
            "prompt_item_ids": [item["id"] for item in items], "entity_ids": entity_ids,
            "entity_version": entity_version, "competitor_pool_hash": competitor_pool_hash,
            "engine_ids": engine_ids, "engine_signature": engine_signature,
            "repeats": repeats, "temperature": legacy_fields["temperature"],
            "system_prompt": legacy_fields["system_prompt"],
            "max_tokens": legacy_fields["max_tokens"], "language": project["language"],
            "market": project["market"], "judge_version": JUDGE_VERSION, "mode": modes.pop(),
            "measurement_target": targets.pop(),
            "valid_sample_definition": "succeeded_nonempty_evidence_v1" if manual_web else VALID_SAMPLE_DEFINITION,
            "stratum_weights": loads(prompt_set["weights_json"], {}),
            "max_safe_retries": int(payload.get("max_safe_retries", 2)),
            "use_judge": use_judge,
            "judge_mode": "disabled" if not use_judge else "independent" if judge_engine else "answer_engine",
            "collection_protocol": collection_protocol,
            "answer_execution": answer_map,
            "judge_signature": judge_signature,
            "judge_execution": judge_map,
            "reported_model_versions": {
                str(engine["id"]): engine["model"] for engine in engines},
        }
        now = utc_now()
        wave_id = conn.execute("INSERT INTO waves(client_id,project_id,prompt_set_id,entity_version,label,anchor_at,protocol_json,stats_json,engine_snapshot_json,judge_snapshot_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                               (project["client_id"], project["id"], prompt_set["id"], entity_version,
                                payload["label"].strip(), payload.get("anchor_at") or now,
                                dumps(protocol), dumps(stats), dumps([engine_execution(engine) for engine in engines]),
                                dumps(engine_execution(judge_engine) if judge_engine else {}), now)).lastrowid
        wave = one(conn, "SELECT * FROM waves WHERE id=?", (wave_id,))
        audit(conn, actor, project, "wave", wave_id, "create", None, wave)
        return wave


def estimate_wave(conn, wave: dict) -> dict:
    return estimate_wave_cost(conn, wave)


def _create_run(conn, project: dict, wave: dict, actor: int | None) -> dict:
    protocol = loads(wave["protocol_json"], {})
    attempt = (one(conn, "SELECT MAX(attempt_no) AS value FROM runs WHERE wave_id=?", (wave["id"],))["value"] or 0) + 1
    prompts = prompt_set_content(conn, protocol["prompt_set_id"])
    engines = [engine_execution(engine) for engine in frozen_engines(conn, wave)]
    manual_web = protocol.get("measurement_target") == "consumer_web"
    judge_engine = loads(wave.get("judge_snapshot_json"), {}) or None
    if not engines:
        raise HTTPException(409, "Wave 缺少冻结的引擎执行快照")
    engine_ids = [int(engine["id"]) for engine in engines]
    check_ids = [*engine_ids, *([int(judge_engine["id"])] if judge_engine else [])]
    current = {row["id"]: row for row in all_rows(
        conn, f"SELECT id,enabled FROM engine_configs WHERE id IN ({','.join('?' for _ in check_ids)})", check_ids)}
    disabled = [str(engine_id) for engine_id in check_ids if not current.get(engine_id) or not current[engine_id]["enabled"]]
    if disabled:
        raise HTTPException(409, f"引擎已停用或不存在，不能创建新 Run：{', '.join(disabled)}")
    entities = [entity_public(row) for row in all_rows(conn,
        f"SELECT * FROM brand_entities WHERE id IN ({','.join('?' * len(protocol['entity_ids']))})", protocol["entity_ids"])]
    snapshot = {"protocol": protocol, "prompts": prompts, "engines": engines,
                "judge_engine": judge_engine, "entities": entities, "created_at": utc_now()}
    run_id = conn.execute("INSERT INTO runs(client_id,project_id,wave_id,attempt_no,status,snapshot_json,started_at) VALUES(?,?,?,?,?,?,?)",
                          (project["client_id"], project["id"], wave["id"], attempt,
                           "running" if manual_web else "queued", dumps(snapshot), utc_now())).lastrowid
    now = utc_now()
    conn.executemany("INSERT INTO answers(client_id,project_id,run_id,prompt_item_id,engine_config_id,round_no,status,model,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     [(project["client_id"], project["id"], run_id, item["id"], engine["id"], round_no,
                       "awaiting_collection" if manual_web else "queued", engine.get("model") if manual_web else None, now)
                      for engine in engines for item in prompts for round_no in range(1, int(protocol["repeats"]) + 1)])
    if manual_web:
        conn.execute("""INSERT INTO web_collections(client_id,project_id,answer_id,status,created_at,updated_at)
                        SELECT client_id,project_id,id,'awaiting_collection',?,? FROM answers WHERE run_id=?""",
                     (now, now, run_id))
    conn.execute("UPDATE waves SET status='running' WHERE id=? AND status IN ('planned','data_ready','data_ready_with_warnings','analyzed')",
                 (wave["id"],))
    audit(conn, actor, project, "run", run_id, "create", None, {"wave_id": wave["id"], "attempt_no": attempt})
    return one(conn, "SELECT * FROM runs WHERE id=?", (run_id,))


def _create_budgeted_run(conn, project: dict, wave: dict, actor: int | None,
                         confirmation_reason: str, allow_manual: bool = False) -> dict:
    protocol = loads(wave["protocol_json"], {})
    if protocol.get("measurement_target") == "consumer_web" and not allow_manual:
        raise HTTPException(409, "人工 Consumer Web 只能由用户显式创建采集 Run，调度器不会自动操作网页")
    estimate = estimate_wave_cost(conn, wave)
    decision = authorize_budget(conn, project, estimate, wave=wave, actor=actor,
                                confirmation_reason=confirmation_reason)
    run = _create_run(conn, project, wave, actor)
    reserve(conn, project, decision, wave=wave, run_id=run["id"], actor=actor)
    if decision.get("override_reason"):
        audit(conn, actor, project, "run", run["id"], "budget_override", None,
              {"reason": decision["override_reason"], "limits": decision["limits"]})
    return run


def create_run(project: dict, wave: dict, actor: int | None, conn=None,
               confirmation_reason: str = "", allow_manual: bool = False) -> dict:
    if conn is not None:
        return _create_budgeted_run(conn, project, wave, actor, confirmation_reason, allow_manual)
    with transaction() as owned:
        return _create_budgeted_run(owned, project, wave, actor, confirmation_reason, allow_manual)


def run_progress(conn, run_id: int) -> dict:
    counts = {row["status"]: row["count"] for row in conn.execute(
        "SELECT status,COUNT(*) AS count FROM answers WHERE run_id=? GROUP BY status", (run_id,))}
    total = sum(counts.values())
    finished = sum(counts.get(status, 0) for status in ("succeeded", "failed", "cancelled"))
    return {"total": total, "finished": finished, "progress": round(finished / total * 100, 1) if total else 0,
            "by_status": counts}


def _record_operations(conn, answer: dict, operations: list[dict], failure: dict | None = None,
                       engine: dict | None = None) -> dict:
    aggregate = Counter()
    project = {"id": answer["project_id"], "client_id": answer["client_id"]}
    recording_engine = engine or answer["engine"]
    recorded_failures = set()
    for operation in operations:
        usage = operation.get("usage") or {}
        for key in ("prompt_tokens", "completion_tokens", "search_calls"):
            aggregate[key] += int(usage.get(key) or 0)
        record_attempt(conn, project=project, engine=recording_engine, operation=operation, answer=answer)
        if operation.get("status") == "failed":
            recorded_failures.add(operation["kind"])
    if failure and failure.get("kind", "answer") not in recorded_failures:
        record_attempt(conn, project=project, engine=recording_engine, answer=answer,
                       operation={**failure, "kind": failure.get("kind", "answer"), "status": "failed"})
    return dict(aggregate)


def _classify_source(url: str, primary: dict, settings: dict) -> str:
    domain = urllib.parse.urlparse(url).hostname or ""
    primary_domain = (primary.get("entity_card") or {}).get("domain", "")
    if primary_domain and (domain == primary_domain or domain.endswith("." + primary_domain)):
        return "官网"
    for configured, category in (settings.get("source_domains") or {}).items():
        if domain == configured or domain.endswith("." + configured):
            return category
    return "其他"


def _insert_citations(conn, answer: dict, citations: list[dict], observations: list[dict], primary: dict, settings: dict) -> None:
    observation_by_url = {}
    for observation in observations:
        for url in observation.get("citation_urls") or []:
            observation_by_url.setdefault(url, []).append(observation.get("db_id"))
    for citation in citations:
        url = citation.get("url") or ""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            continue
        content_hash = hashlib.sha256((citation.get("title", "") + citation.get("text", "")).encode()).hexdigest()
        linked = observation_by_url.get(url) or []
        conn.execute("INSERT OR IGNORE INTO citations(client_id,project_id,answer_id,observation_id,raw_url,final_url,title,domain,source_type,content_hash,returned_at,origin) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                     (answer["client_id"], answer["project_id"], answer["id"], linked[0] if len(linked) == 1 else None,
                      url, citation.get("final_url") or "", citation.get("title") or "", parsed.hostname,
                      "人工记录的页面引用" if citation.get("origin") == "manual_page" else _classify_source(url, primary, settings),
                      content_hash, citation.get("returned_at") or utc_now(), citation.get("origin") or "provider_returned"))


def _insert_discovered(conn, answer: dict, discovered: list[dict], actor: int | None = None) -> None:
    existing = {row["name"].casefold() for row in conn.execute("SELECT name FROM brand_entities WHERE project_id=?", (answer["project_id"],))}
    for item in discovered:
        if item["name"].casefold() in existing:
            continue
        now = utc_now()
        conn.execute("INSERT INTO brand_entities(client_id,project_id,logical_id,role,name,entity_card_json,version,valid_from,status,created_at) VALUES(?,?,?,'candidate',?,?,1,?,'pending_review',?)",
                     (answer["client_id"], answer["project_id"], logical_id("discovered"), item["name"],
                      dumps({"aliases": item.get("aliases") or [], "category": item.get("category") or "",
                             "evidence": item.get("evidence") or ""}), now, now))
        existing.add(item["name"].casefold())


def _store_observations(conn, answer: dict, observations: list[dict], actor: int | None = None) -> list[dict]:
    stored = []
    for observation in observations:
        cursor = conn.execute("INSERT OR IGNORE INTO observations(client_id,project_id,answer_id,brand_entity_id,revision,entity_status,mentioned,depth,sentiment,top_choice,evidence,citation_urls_json,discovered_json,judge_status,judge_meta_json,review_status,review_reason,reviewer_id,created_at) VALUES(?,?,?,?,1,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (answer["client_id"], answer["project_id"], answer["id"], observation["brand_entity_id"],
                               observation["entity_status"], observation.get("mentioned", 0), observation.get("depth", "absent"),
                               observation.get("sentiment", "unknown"), observation.get("top_choice", 0),
                               observation.get("evidence") or "", dumps(observation.get("citation_urls") or []),
                               dumps(observation.get("discovered") or []), observation.get("judge_status") or "unknown",
                               dumps(observation.get("judge_meta") or {}), observation.get("review_status") or "machine",
                               observation.get("review_reason") or "", actor, utc_now()))
        stored.append({**observation, "db_id": cursor.lastrowid})
    return stored


def _answer_context(conn, answer_id: int) -> dict | None:
    answer = one(conn, "SELECT a.*,r.wave_id,r.snapshot_json,r.cancel_requested,w.protocol_json,w.engine_snapshot_json,w.judge_snapshot_json,p.settings_json FROM answers a JOIN runs r ON r.id=a.run_id JOIN waves w ON w.id=r.wave_id JOIN projects p ON p.id=a.project_id WHERE a.id=?", (answer_id,))
    if not answer:
        return None
    answer["snapshot"] = loads(answer["snapshot_json"], {})
    answer["protocol"] = answer["snapshot"].get("protocol") or loads(answer["protocol_json"], {})
    answer["settings"] = loads(answer["settings_json"], {})
    engines = answer["snapshot"].get("engines") or frozen_engines(conn, answer)
    answer["engine"] = next((engine for engine in engines
                             if int(engine["id"]) == int(answer["engine_config_id"])), None)
    answer["judge_engine"] = answer["snapshot"].get("judge_engine") or loads(answer.get("judge_snapshot_json"), {}) or None
    answer["prompt"] = next((item for item in answer["snapshot"].get("prompts", [])
                             if int(item["id"]) == int(answer["prompt_item_id"])), None)
    if not answer["prompt"]:
        answer["prompt"] = one(conn, "SELECT * FROM prompt_items WHERE id=?", (answer["prompt_item_id"],))
    answer["entities"] = answer["snapshot"].get("entities") or [entity_public(row) for row in all_rows(conn,
        f"SELECT * FROM brand_entities WHERE id IN ({','.join('?' * len(answer['protocol']['entity_ids']))})",
        answer["protocol"]["entity_ids"])]
    return answer


def _claim_answer() -> dict | None:
    with transaction() as conn:
        row = one(conn, "SELECT a.id,a.run_id FROM answers a JOIN runs r ON r.id=a.run_id WHERE a.status IN ('queued','judging') AND r.cancel_requested=0 AND r.status IN ('queued','running') ORDER BY a.id LIMIT 1")
        if not row:
            return None
        conn.execute("UPDATE answers SET status='running' WHERE id=?", (row["id"],))
        conn.execute("UPDATE runs SET status='running',started_at=COALESCE(started_at,?) WHERE id=?", (utc_now(), row["run_id"]))
        return row


def _finalize_run(conn, run_id: int) -> None:
    remaining = one(conn, "SELECT COUNT(*) AS count FROM answers WHERE run_id=? AND status IN ('queued','running','judging','awaiting_collection')", (run_id,))["count"]
    if remaining:
        return
    counts = {row["status"]: row["count"] for row in conn.execute("SELECT status,COUNT(*) AS count FROM answers WHERE run_id=? GROUP BY status", (run_id,))}
    run = one(conn, "SELECT * FROM runs WHERE id=?", (run_id,))
    succeeded = counts.get("succeeded", 0)
    if run["cancel_requested"]:
        status = "cancelled"
    elif succeeded == 0:
        status = "failed"
    elif counts.get("failed", 0) or counts.get("cancelled", 0):
        status = "partial"
    else:
        status = "done"
    snapshot = loads(run["snapshot_json"], {})
    reported = {str(row["engine_config_id"]): row["model"] for row in conn.execute(
        "SELECT DISTINCT engine_config_id,model FROM answers WHERE run_id=? AND model IS NOT NULL", (run_id,))}
    snapshot.setdefault("protocol", {})["reported_model_versions"] = reported
    conn.execute("UPDATE runs SET status=?,finished_at=?,snapshot_json=? WHERE id=?", (status, utc_now(), dumps(snapshot), run_id))
    release_budget(conn=conn, run_id=run_id)
    wave_status = "data_ready" if status == "done" else "data_ready_with_warnings"
    conn.execute("UPDATE waves SET status=? WHERE id=? AND status='running'", (wave_status, run["wave_id"]))
    if status in ("partial", "failed"):
        conn.execute("INSERT INTO alerts(client_id,project_id,wave_id,kind,severity,message,created_at) SELECT client_id,project_id,wave_id,'run_incomplete','warning',?,? FROM runs WHERE id=?",
                     (f"Run {run_id} 状态为 {status}，请检查失败样本；缺失不计为零提及。", utc_now(), run_id))


def process_answer(answer_id: int) -> None:
    with connect() as conn:
        context = _answer_context(conn, answer_id)
    if not context:
        return
    if not context["engine"]:
        context["engine"] = {"id": context["engine_config_id"], "kind": "missing", "cost_rule": {}}
    engine = context["engine"]
    protocol = context["protocol"]
    entities = context["entities"]
    provider = None
    raw_text = context["raw_text"]
    citations: list[dict] = []
    answer_usage = loads(context["usage_json"], {})
    manual_web = engine.get("kind") == "manual_web"
    if manual_web and not raw_text:
        with transaction() as conn:
            conn.execute("UPDATE answers SET status='failed',valid_sample=0,error_type='collection_missing',error_detail='人工回答尚未完整提交',completed_at=? WHERE id=?",
                         (utc_now(), answer_id))
            _finalize_run(conn, context["run_id"])
        return
    if manual_web:
        with connect() as conn:
            collection = one(conn, "SELECT * FROM web_collections WHERE answer_id=?", (answer_id,))
        citations = loads(collection["citations_json"], []) if collection else []
        for citation in citations:
            citation["origin"] = "manual_page"
            citation["returned_at"] = collection.get("observed_at") or utc_now()
    if not raw_text:
        try:
            provider = build_provider(engine, SecretStore().get(engine.get("secret_ref", "")),
                                      [entity["name"] for entity in sorted(entities, key=lambda item: item["role"] != "primary")])
            with _engine_slot(engine):
                result = provider.ask(context["prompt"]["text"], answer_execution_for(protocol, context["engine_config_id"]))
            raw_text, citations = result.text, result.citations
            cancel_after_answer = False
            with transaction() as conn:
                usage = _record_operations(conn, context, result.operations)
                conn.execute("UPDATE answers SET raw_text=?,raw_text_sha256=?,status='judging',usage_json=?,model=?,completed_at=NULL,valid_sample=NULL,content_retained=1 WHERE id=? AND raw_text IS NULL",
                             (raw_text, hashlib.sha256(raw_text.encode("utf-8")).hexdigest(), dumps(usage), result.model, answer_id))
                answer_usage = usage
                cancel_after_answer = bool(one(conn, "SELECT cancel_requested FROM runs WHERE id=?", (context["run_id"],))["cancel_requested"])
                if cancel_after_answer:
                    conn.execute("UPDATE answers SET status='cancelled',valid_sample=0 WHERE id=?", (answer_id,))
                    _finalize_run(conn, context["run_id"])
            if cancel_after_answer:
                return
        except ProviderError as error:
            retry = False
            with transaction() as conn:
                _record_operations(conn, context, error.operations,
                                   {"kind": "search" if error.kind.startswith("search") else "answer",
                                    "error_type": error.kind, "error_detail": str(error)[:1000]})
                attempts = one(conn, "SELECT COUNT(*) AS count FROM call_attempts WHERE answer_id=? AND status='failed' AND kind IN ('answer','search')", (answer_id,))["count"]
                cancelled = bool(one(conn, "SELECT cancel_requested FROM runs WHERE id=?", (context["run_id"],))["cancel_requested"])
                retry = (error.retryable and not error.outcome_unknown and not cancelled
                         and attempts <= int(protocol.get("max_safe_retries", 2)))
                status = "queued" if retry else "cancelled" if cancelled else "failed"
                conn.execute("UPDATE answers SET status=?,error_type=?,error_detail=?,completed_at=?,valid_sample=? WHERE id=?",
                             (status, error.kind, str(error)[:1000], None if retry else utc_now(),
                              None if retry else 0, answer_id))
                if not retry:
                    _finalize_run(conn, context["run_id"])
            if retry:
                time.sleep(min(2 ** attempts, 8))
            return
        except Exception as error:
            with transaction() as conn:
                _record_operations(conn, context, [], {"kind": "answer", "error_type": type(error).__name__,
                                                       "error_detail": str(error)[:1000]})
                conn.execute("UPDATE answers SET status='failed',error_type=?,error_detail=?,completed_at=?,valid_sample=0 WHERE id=?",
                             (type(error).__name__, str(error)[:1000], utc_now(), answer_id))
                _finalize_run(conn, context["run_id"])
            return
    independent_judge = context.get("judge_engine")
    demo = engine["kind"] == "demo" and not independent_judge
    observations = fallback_observations(raw_text, entities, demo=demo)
    discovered: list[dict] = []
    if protocol.get("use_judge") and not demo:
        judge_engine = independent_judge or engine
        if not judge_engine or judge_engine.get("kind") == "manual_web":
            for observation in observations:
                observation["judge_status"] = "judge-config-missing"
                observation["review_status"] = "pending"
        else:
            try:
                judge_execution = judge_execution_for(protocol, context["engine_config_id"])
                if judge_engine.get("kind") == "demo":
                    observations = fallback_observations(raw_text, entities, demo=True)
                    operations = [{"kind": "judge", "status": "succeeded", "model": "geopulse-demo-judge",
                                   "usage": {}, "request_id": "demo-judge",
                                   "request_params": {key: judge_execution.get(key) for key in ("temperature", "max_tokens", "json_mode")}}]
                else:
                    provider = build_provider(judge_engine, SecretStore().get(judge_engine.get("secret_ref", "")),
                                              [entity["name"] for entity in sorted(entities, key=lambda item: item["role"] != "primary")])
                    with _engine_slot(judge_engine):
                        observations, discovered, judged = judge_answer(provider, raw_text, entities, judge_execution, citations)
                    operations = judged.operations
                with transaction() as conn:
                    _record_operations(conn, context, operations, engine=judge_engine)
            except Exception as error:
                observations = fallback_observations(raw_text, entities, demo=False)
                kind = error.kind if isinstance(error, ProviderError) else "judge_invalid"
                with transaction() as conn:
                    _record_operations(conn, context, error.operations if isinstance(error, ProviderError) else [],
                                       {"kind": "judge", "error_type": kind, "error_detail": str(error)[:1000]},
                                       engine=judge_engine)
    with transaction() as conn:
        stored = _store_observations(conn, {"id": answer_id, **context}, observations)
        primary = next(entity for entity in entities if entity["role"] == "primary")
        _insert_citations(conn, context, citations, stored, primary, context["settings"])
        _insert_discovered(conn, context, discovered)
        conn.execute("UPDATE answers SET status='succeeded',completed_at=?,valid_sample=1,content_retained=1 WHERE id=?", (utc_now(), answer_id))
        _finalize_run(conn, context["run_id"])


class Worker:
    def __init__(self, count: int | None = None):
        self.count = count or config.worker_count()
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []

    def recover(self) -> None:
        with transaction() as conn:
            conn.execute("UPDATE answers SET status='queued' WHERE status='running' AND raw_text IS NULL")
            conn.execute("UPDATE answers SET status='judging' WHERE status='running' AND raw_text IS NOT NULL")
            conn.execute("UPDATE answers SET status='judging' WHERE status='judging' AND raw_text IS NOT NULL")
            idle_runs = all_rows(conn, "SELECT id FROM runs r WHERE status IN ('queued','running') AND NOT EXISTS (SELECT 1 FROM answers a WHERE a.run_id=r.id AND a.status IN ('queued','running','judging','awaiting_collection'))")
            for run in idle_runs:
                _finalize_run(conn, run["id"])

    def start(self) -> None:
        if self.threads:
            return
        self.recover()
        self.stop_event.clear()
        self.threads = [threading.Thread(target=self._loop, name=f"geopulse-worker-{index}", daemon=True)
                        for index in range(self.count)]
        for thread in self.threads:
            thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=2)
        self.threads = []

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            claimed = _claim_answer()
            if not claimed:
                self.stop_event.wait(0.15)
                continue
            try:
                process_answer(claimed["id"])
            except Exception as error:
                with transaction() as conn:
                    answer = one(conn, "SELECT status FROM answers WHERE id=?", (claimed["id"],))
                    if answer and answer["status"] in ("queued", "running", "judging"):
                        conn.execute("UPDATE answers SET status='failed',valid_sample=0,error_type=?,error_detail=?,completed_at=? WHERE id=?",
                                     (type(error).__name__, str(error)[:1000], utc_now(), claimed["id"]))
                    _finalize_run(conn, claimed["run_id"])


def load_run_samples(conn, run: dict) -> tuple[list[dict], dict]:
    snapshot = loads(run["snapshot_json"], {})
    protocol = snapshot.get("protocol") or snapshot
    entities = snapshot.get("entities") or []
    primary_id = next((int(entity["id"]) for entity in entities if entity.get("role") == "primary"), None)
    if primary_id is None:
        primary_id = next((entity_id for entity_id in protocol.get("entity_ids", [])
                           if (one(conn, "SELECT role FROM brand_entities WHERE id=?", (entity_id,)) or {}).get("role") == "primary"), None)
    engines = {int(engine["id"]): engine for engine in snapshot.get("engines", [])}
    answers = all_rows(conn, "SELECT a.*,p.canonical_intent_id,p.text AS prompt_text,p.dimension,p.query_type,p.priority,p.eligibility FROM answers a JOIN prompt_items p ON p.id=a.prompt_item_id WHERE a.run_id=? ORDER BY a.id", (run["id"],))
    weights = protocol.get("stratum_weights") or {}
    for answer in answers:
        engine = engines.get(int(answer["engine_config_id"]), {})
        answer["engine_name"] = engine.get("name") or str(answer["engine_config_id"])
        answer["engine_mode"] = engine.get("mode") or protocol.get("mode") or "memory"
        answer["engine_kind"] = engine.get("kind") or "unknown"
        answer["measurement_target"] = protocol.get("measurement_target") or "provider_api"
        if answer["measurement_target"] == "consumer_web":
            collection = one(conn, "SELECT status,failure_type,retrieval_status FROM web_collections WHERE answer_id=?", (answer["id"],)) or {}
            answer["collection_status"] = collection.get("status") or "missing"
            answer["collection_failure_type"] = collection.get("failure_type") or ""
            answer["retrieval_status"] = collection.get("retrieval_status") or "unknown"
            answer["evidence_screenshots"] = one(conn, "SELECT COUNT(*) AS count FROM answer_attachments WHERE answer_id=? AND kind='screenshot' AND content IS NOT NULL AND purged_at IS NULL", (answer["id"],))["count"]
            answer["evidence_complete"] = bool(answer.get("raw_text_sha256") and answer["evidence_screenshots"] and collection.get("status") == "completed")
        observations = all_rows(conn, "SELECT o.*,b.name,b.role FROM observations o JOIN brand_entities b ON b.id=o.brand_entity_id WHERE o.answer_id=? ORDER BY o.brand_entity_id,o.revision DESC", (answer["id"],))
        latest = {}
        for observation in observations:
            if observation["brand_entity_id"] in latest:
                continue
            observation["citation_urls"] = loads(observation.pop("citation_urls_json"), [])
            observation["judge_meta"] = loads(observation.pop("judge_meta_json"), {})
            observation["discovered"] = loads(observation.pop("discovered_json"), [])
            latest[observation["brand_entity_id"]] = observation
        answer["observations"] = list(latest.values())
        answer["weight"] = float(weights.get(answer["canonical_intent_id"],
                                   weights.get(answer["dimension"], weights.get(answer["query_type"], 1))) or 1)
    return answers, {"primary_id": primary_id, "protocol": protocol}
