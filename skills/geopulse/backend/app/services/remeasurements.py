"""Cohort-level remeasurement rounds with frozen official-Run evidence."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from ..db import all_rows, dumps, loads, one, transaction, utc_now
from ..engine.compare import compare_metrics
from ..engine.metrics import calculate_metrics
from ..security import audit
from .interventions import observation_hash
from .measurement import load_run_samples
from .state import transition


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not parsed.tzinfo:
        raise HTTPException(400, "复测锚点必须包含时区")
    return parsed


def create_rounds(conn, action: dict, actor: int, items: list[dict], allow_baseline: bool = False) -> list[dict]:
    if action["status"] not in ("published", "remeasure_due"):
        raise HTTPException(409, "只有已发布 cohort 可以安排复测")
    publication = one(conn, "SELECT * FROM asset_publications WHERE action_id=? ORDER BY id LIMIT 1", (action["id"],))
    if not publication:
        raise HTTPException(409, "复测必须从首条真实渠道发布时间计算")
    opportunity = one(conn, "SELECT * FROM opportunities WHERE id=?", (action["opportunity_id"],))
    baseline = one(conn, "SELECT * FROM waves WHERE id=? AND project_id=?", (opportunity["wave_id"], action["project_id"]))
    if not baseline or not baseline["official_run_id"]:
        raise HTTPException(409, "机会基线 Wave 缺少正式 Run")
    anchor = _parse(publication["published_at"])
    brief = one(conn, "SELECT success_criteria FROM content_briefs WHERE action_id=? AND status='approved' ORDER BY version DESC LIMIT 1",
                (action["id"],))
    created = []
    for item in items:
        days = int(item.get("offset_days") or item.get("remeasure_days") or 14)
        target = one(conn, "SELECT * FROM waves WHERE id=? AND project_id=? AND client_id=?",
                     (int(item["target_wave_id"]), action["project_id"], action["client_id"]))
        if not target:
            raise HTTPException(404, "目标 Wave 不存在或不属于当前项目")
        if target["id"] == baseline["id"] and not allow_baseline:
            raise HTTPException(409, "复测目标不能是机会来源的基线 Wave")
        duplicate = one(conn, """SELECT id FROM action_remeasurement_rounds WHERE action_id=?
            AND (offset_days=? OR target_wave_id=?) AND status!='legacy_unavailable'""",
                        (action["id"], days, target["id"]))
        if duplicate:
            raise HTTPException(409, "同一 cohort 的天数节点和目标 Wave 必须各自独立，不能重复创建")
        due_at = _iso(anchor + timedelta(days=days))
        round_no = (one(conn, "SELECT MAX(round_no) AS value FROM action_remeasurement_rounds WHERE action_id=?",
                        (action["id"],))["value"] or 0) + 1
        surface = loads(target["protocol_json"], {}).get("measurement_target", "provider_api")
        now = utc_now()
        round_id = conn.execute("""INSERT INTO action_remeasurement_rounds(client_id,project_id,action_id,round_no,offset_days,
            baseline_wave_id,baseline_run_id,target_wave_id,surface,due_at,success_criteria,created_by,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (action["client_id"], action["project_id"], action["id"], round_no, days, baseline["id"],
             baseline["official_run_id"], target["id"], surface, due_at,
             item.get("success_criteria") or (brief or {}).get("success_criteria") or "", actor, now)).lastrowid
        if surface != "consumer_web":
            conn.execute("""INSERT INTO schedules(client_id,project_id,wave_id,scheduled_at,next_run_at,anchor_at,action_id,
                remeasurement_round_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (action["client_id"], action["project_id"], target["id"], due_at, due_at,
                 publication["published_at"], action["id"], round_id, now, now))
        row = one(conn, "SELECT * FROM action_remeasurement_rounds WHERE id=?", (round_id,))
        audit(conn, actor, action, "remeasurement_round", round_id, "create", None, row)
        created.append(row)
    if created and action["status"] == "published":
        transition(conn, "actions", action, "remeasure_due", actor, "创建 cohort 复测节点",
                   {"target_wave_id": created[0]["target_wave_id"]})
    return created


def _run_metrics(conn, wave: dict, run_id: int) -> tuple[dict, dict, dict]:
    run = one(conn, "SELECT * FROM runs WHERE id=? AND wave_id=? AND project_id=?",
              (run_id, wave["id"], wave["project_id"]))
    if not run or run["status"] not in ("done", "partial"):
        raise HTTPException(409, "固定正式 Run 不存在、不属于该 Wave 或尚未完成")
    samples, context = load_run_samples(conn, run)
    metrics = calculate_metrics(samples, context["primary_id"], loads(wave["stats_json"], {}))
    protocol = loads(run["snapshot_json"], {}).get("protocol") or context["protocol"]
    return metrics, protocol, run


def _evidence_refs(conn, run_ids: list[int]) -> list[dict]:
    marks = ",".join("?" for _ in run_ids)
    refs = []
    for answer in all_rows(conn, f"""SELECT id,run_id,raw_text_sha256,content_retained FROM answers
        WHERE run_id IN ({marks}) ORDER BY id""", run_ids):
        refs.append({"kind": "answer", "answer_id": answer["id"], "run_id": answer["run_id"],
                     "hash": answer.get("raw_text_sha256") or "", "content_retained": bool(answer.get("content_retained", 1))})
    for observation in all_rows(conn, f"""SELECT o.* FROM observations o JOIN answers a ON a.id=o.answer_id
        WHERE a.run_id IN ({marks}) ORDER BY o.id""", run_ids):
        refs.append({"kind": "observation", "answer_id": observation["answer_id"], "observation_id": observation["id"],
                     "revision": observation["revision"], "hash": observation_hash(observation)})
    for citation in all_rows(conn, f"""SELECT c.id,c.answer_id,c.observation_id,c.content_hash FROM citations c
        JOIN answers a ON a.id=c.answer_id WHERE a.run_id IN ({marks}) ORDER BY c.id""", run_ids):
        refs.append({"kind": "citation", "answer_id": citation["answer_id"], "observation_id": citation.get("observation_id"),
                     "citation_id": citation["id"], "hash": citation["content_hash"]})
    return refs


def assess_round(conn, round_row: dict, actor: int, reason: str = "") -> dict:
    if round_row["status"] != "pending_measurement":
        raise HTTPException(409, "该轮评估已冻结或为 legacy 历史，不能覆盖；需要新证据时请创建新轮次")
    baseline = one(conn, "SELECT * FROM waves WHERE id=? AND project_id=?",
                   (round_row["baseline_wave_id"], round_row["project_id"]))
    target = one(conn, "SELECT * FROM waves WHERE id=? AND project_id=?",
                 (round_row["target_wave_id"], round_row["project_id"]))
    if not round_row["baseline_run_id"]:
        raise HTTPException(409, "legacy 轮次没有固定基线 Run，不能补造历史评估")
    if not target or not target["official_run_id"]:
        raise HTTPException(409, "目标 Wave 尚未由管理员指定正式 Run，不能确认复测结果")
    if target["id"] == baseline["id"]:
        raise HTTPException(409, "复测目标不能是机会来源的基线 Wave，请先执行并指定另一轮正式测量")
    before, before_protocol, baseline_run = _run_metrics(conn, baseline, round_row["baseline_run_id"])
    after, after_protocol, target_run = _run_metrics(conn, target, target["official_run_id"])
    comparison = compare_metrics(before, after, before_protocol, after_protocol,
                                 float(loads(target["stats_json"], {}).get("min_pair_completeness", 0.9)))
    project = one(conn, "SELECT * FROM projects WHERE id=?", (round_row["project_id"],))
    minimum = int(loads(project["settings_json"], {}).get("small_sample_n", 30))
    sufficient = min(before["quality"]["valid_samples"], after["quality"]["valid_samples"]) >= minimum
    if not comparison.get("comparable"):
        status = "incomparable" if comparison.get("mismatches") else "insufficient_evidence"
        observed = "unknown"
    elif not sufficient:
        status = "insufficient_evidence"
        observed = "unknown"
    else:
        status = "measured"
        opportunity = one(conn, "SELECT o.* FROM opportunities o JOIN actions a ON a.opportunity_id=o.id WHERE a.id=?",
                          (round_row["action_id"],))
        delta = comparison["delta"]
        if opportunity["gap_type"] == "被贬":
            improved = after["negative_risk_rate"]["value"] < before["negative_risk_rate"]["value"]
        elif opportunity["gap_type"] == "深度落后":
            improved = delta["effective_recommendation_rate"]["pp"] > 0 or delta["hit_rate"]["pp"] > 0
        else:
            improved = delta["coverage"]["pp"] > 0 or delta["hit_rate"]["pp"] > 0
        observed = "improved" if improved else "not_improved"
    refs = _evidence_refs(conn, [baseline_run["id"], target_run["id"]])
    digest = hashlib.sha256(dumps(comparison).encode()).hexdigest()
    now = utc_now()
    explanation = reason.strip() or (
        "固定基线与目标正式 Run，仅记录 cohort 同期观察，不作单资产或策略因果归因。"
        if status == "measured" else comparison.get("reason") or "有效样本低于冻结的小样本阈值，仅保留证据不足结论。")
    conn.execute("""UPDATE action_remeasurement_rounds SET target_run_id=?,status=?,observed_change=?,comparison_json=?,
        comparison_hash=?,evidence_refs_json=?,conclusion_reason=?,assessed_by=?,assessed_at=? WHERE id=?""",
        (target_run["id"], status, observed, dumps(comparison), digest, dumps(refs), explanation, actor, now, round_row["id"]))
    action = one(conn, "SELECT * FROM actions WHERE id=?", (round_row["action_id"],))
    conn.execute("""INSERT INTO external_events(client_id,project_id,event_at,kind,description,source,created_by,created_at,
        action_id,remeasurement_round_id) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (action["client_id"], action["project_id"], now, "复测评估",
         f"D{round_row['offset_days']} cohort 复测：{status} / {observed or 'unknown'}", "", actor, now,
         action["id"], round_row["id"]))
    opportunity = one(conn, "SELECT * FROM opportunities WHERE id=?", (action["opportunity_id"],))
    if opportunity["status"] == "actioned":
        transition(conn, "opportunities", opportunity, "remeasured", actor, explanation)
    row = one(conn, "SELECT * FROM action_remeasurement_rounds WHERE id=?", (round_row["id"],))
    audit(conn, actor, action, "remeasurement_round", row["id"], "assess", round_row, row)
    return row


def remind_due_consumer_rounds() -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reminded = 0
    with transaction() as conn:
        rounds = all_rows(conn, """SELECT * FROM action_remeasurement_rounds WHERE status='pending_measurement'
            AND surface='consumer_web' AND due_at<=? AND reminder_at IS NULL ORDER BY id""", (now,))
        for row in rounds:
            conn.execute("""INSERT INTO alerts(client_id,project_id,wave_id,kind,severity,message,dedupe_key,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                (row["client_id"], row["project_id"], row["target_wave_id"], "remeasurement_due", "warning",
                 f"Action {row['action_id']} 的 D{row['offset_days']} Consumer Web 复测已到期；请显式创建并确认采集 Run，系统不会自动操作网页。",
                 f"remeasurement-round:{row['id']}", now, now))
            conn.execute("UPDATE action_remeasurement_rounds SET reminder_at=? WHERE id=? AND reminder_at IS NULL",
                         (now, row["id"]))
            reminded += 1
    return reminded
