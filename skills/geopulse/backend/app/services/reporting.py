"""Immutable report snapshots, release gates and HTML rendering."""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import HTTPException
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..db import all_rows, dumps, loads, one, utc_now
from ..engine.compare import compare_metrics
from ..engine.metrics import calculate_metrics, ratio
from ..security import audit
from .measurement import load_run_samples
from .state import transition

TEMPLATES = Environment(loader=FileSystemLoader(str(Path(__file__).parent.parent / "templates")),
                        autoescape=select_autoescape(["html", "xml"]))


def wave_metrics(conn, wave: dict, allow_empty: bool = False) -> tuple[dict, dict, dict | None]:
    protocol = loads(wave["protocol_json"], {})
    if not wave["official_run_id"]:
        if not allow_empty:
            raise HTTPException(409, f"Wave {wave['label']} 尚未指定正式 run")
        primary_id = next((entity["id"] for entity in (one(conn, "SELECT id,role FROM brand_entities WHERE id=?", (entity_id,))
                                                       for entity_id in protocol.get("entity_ids", []))
                           if entity and entity["role"] == "primary"), 0)
        metrics = calculate_metrics([], primary_id, loads(wave["stats_json"], {}))
        expected = len(protocol.get("prompt_item_ids", [])) * len(protocol.get("engine_ids", [])) * int(protocol.get("repeats", 1))
        metrics["quality"]["expected_samples"] = expected
        metrics["quality"]["valid_sample_rate"] = ratio(0, expected, loads(wave["stats_json"], {}))
        return metrics, protocol, None
    run = one(conn, "SELECT * FROM runs WHERE id=? AND wave_id=? AND project_id=?",
              (wave["official_run_id"], wave["id"], wave["project_id"]))
    if not run:
        raise HTTPException(409, "正式 run 不属于该 wave")
    samples, context = load_run_samples(conn, run)
    metrics = calculate_metrics(samples, context["primary_id"], loads(wave["stats_json"], {}))
    protocol = loads(run["snapshot_json"], {}).get("protocol") or context["protocol"]
    return metrics, protocol, run


def _costs(conn, run_ids: list[int]) -> dict:
    if not run_ids:
        return {"amount": 0, "unknown": False, "by_kind": {}, "tokens": {}}
    marks = ",".join("?" * len(run_ids))
    by_kind = {row["kind"]: round(row["cost"] or 0, 6) for row in conn.execute(
        f"SELECT kind,SUM(cost) AS cost FROM call_attempts WHERE answer_id IN (SELECT id FROM answers WHERE run_id IN ({marks})) GROUP BY kind", run_ids)}
    unknown = one(conn, f"SELECT COUNT(*) AS count FROM call_attempts WHERE cost IS NULL AND answer_id IN (SELECT id FROM answers WHERE run_id IN ({marks}))", run_ids)["count"] > 0
    tokens = {row["kind"]: {"prompt_tokens": 0, "completion_tokens": 0} for row in conn.execute(
        f"SELECT DISTINCT kind FROM call_attempts WHERE answer_id IN (SELECT id FROM answers WHERE run_id IN ({marks}))", run_ids)}
    for row in conn.execute(f"SELECT kind,usage_json FROM call_attempts WHERE answer_id IN (SELECT id FROM answers WHERE run_id IN ({marks}))", run_ids):
        usage = loads(row["usage_json"], {})
        for key in ("prompt_tokens", "completion_tokens"):
            tokens[row["kind"]][key] += int(usage.get(key) or 0)
    return {"amount": round(sum(by_kind.values()), 6), "unknown": unknown, "by_kind": by_kind, "tokens": tokens}


def _source_structure(conn, run_ids: list[int]) -> list[dict]:
    if not run_ids:
        return []
    marks = ",".join("?" * len(run_ids))
    return all_rows(conn, f"""SELECT c.source_type,c.domain,COALESCE(b.role,'unattributed') AS entity_role,
        COUNT(*) AS citations,COUNT(DISTINCT c.raw_url) AS unique_sources
        FROM citations c JOIN answers a ON a.id=c.answer_id
        LEFT JOIN observations o ON o.id=c.observation_id
        LEFT JOIN brand_entities b ON b.id=o.brand_entity_id
        WHERE a.run_id IN ({marks}) GROUP BY c.source_type,c.domain,entity_role
        ORDER BY c.source_type,c.domain,entity_role""", run_ids)


def build_snapshot(conn, project: dict, wave_ids: list[int], actor: int) -> dict:
    if not wave_ids or len(wave_ids) > 2:
        raise HTTPException(400, "报告需要一个诊断 wave 或 baseline+current 两个 wave")
    waves = [one(conn, "SELECT * FROM waves WHERE id=? AND project_id=? AND client_id=?",
                 (wave_id, project["id"], project["client_id"])) for wave_id in wave_ids]
    if any(wave is None for wave in waves):
        raise HTTPException(404, "wave 不存在或不属于当前项目")
    wave_payload = []
    run_ids = []
    internal_samples = []
    for wave in waves:
        metrics, protocol, run = wave_metrics(conn, wave, allow_empty=True)
        public_metrics = {key: value for key, value in metrics.items() if key != "pairs"}
        wave_payload.append({"wave": {key: value for key, value in wave.items() if key not in ("protocol_json", "stats_json")},
                             "protocol": protocol, "stats": loads(wave["stats_json"], {}),
                             "run": ({"id": run["id"], "attempt_no": run["attempt_no"], "status": run["status"]} if run else None),
                             "metrics": public_metrics})
        if run:
            run_ids.append(run["id"])
            samples, _ = load_run_samples(conn, run)
            internal_samples.extend({"id": sample["id"], "run_id": run["id"], "prompt_text": sample["prompt_text"],
                                     "engine_name": sample["engine_name"], "round_no": sample["round_no"],
                                     "status": sample["status"], "raw_text": sample["raw_text"],
                                     "error_type": sample["error_type"], "error_detail": sample["error_detail"],
                                     "observations": sample["observations"]} for sample in samples)
    comparison = None
    if len(waves) == 2:
        if len(run_ids) != 2:
            comparison = {"comparable": False, "reason": "两次测量都需要先由管理员指定正式 run"}
        else:
            first_samples, first_context = load_run_samples(conn, one(conn, "SELECT * FROM runs WHERE id=?", (run_ids[0],)))
            second_samples, second_context = load_run_samples(conn, one(conn, "SELECT * FROM runs WHERE id=?", (run_ids[1],)))
            first = calculate_metrics(first_samples, first_context["primary_id"], loads(waves[0]["stats_json"], {}))
            second = calculate_metrics(second_samples, second_context["primary_id"], loads(waves[1]["stats_json"], {}))
            comparison = compare_metrics(first, second, wave_payload[0]["protocol"], wave_payload[1]["protocol"],
                                         float(loads(waves[1]["stats_json"], {}).get("min_pair_completeness", 0.9)))
    marks = ",".join("?" * len(wave_ids))
    opportunities = all_rows(conn, f"SELECT o.*,p.text AS prompt_text,p.dimension FROM opportunities o JOIN prompt_items p ON p.id=o.prompt_item_id WHERE o.project_id=? AND o.wave_id IN ({marks}) AND o.status IN ('confirmed','actioned','remeasured','closed') ORDER BY o.score DESC", [project["id"], *wave_ids])
    for opportunity in opportunities:
        opportunity["evidence"] = loads(opportunity.pop("evidence_json"), {})
        opportunity["score_detail"] = loads(opportunity.pop("score_json"), {})
    actions = all_rows(conn, f"SELECT * FROM actions WHERE project_id=? ORDER BY updated_at DESC", (project["id"],))
    events = all_rows(conn, "SELECT * FROM external_events WHERE project_id=? ORDER BY event_at", (project["id"],))
    latest = wave_payload[-1]["metrics"]
    if not latest["quality"]["valid_samples"]:
        diagnosis = "本周期无有效样本，无法诊断。请先检查引擎配置、失败样本和正式 run。"
    elif comparison and not comparison.get("comparable"):
        diagnosis = comparison.get("reason") or "两次测量不可严格比较"
    else:
        measured_dimensions = [item for item in latest["dimensions"] if item["coverage"]["n"]]
        worst = min(measured_dimensions, key=lambda item: item["coverage"]["value"], default=None)
        diagnosis = (f"已测得有效推荐率为 {latest['effective_recommendation_rate']['hits']}/{latest['effective_recommendation_rate']['n']}"
                     f"（{latest['effective_recommendation_rate']['value']}%）。")
        if worst and worst["coverage"]["value"] < 100:
            diagnosis += f"覆盖率最低的已测维度为{worst['key']}（{worst['coverage']['hits']}/{worst['coverage']['n']}）。"
        diagnosis += "样本与口径限制见下文，不作策略因果断言。"
    return {"schema_version": 1, "project": {"id": project["id"], "client_id": project["client_id"],
            "name": project["name"], "category": project["category"], "market": project["market"],
            "language": project["language"], "timezone": project["timezone"]},
            "waves": wave_payload, "comparison": comparison, "opportunities": opportunities,
            "actions": actions, "external_events": events, "costs": _costs(conn, run_ids),
            "source_structure": _source_structure(conn, run_ids), "internal_samples": internal_samples,
            "diagnosis": diagnosis, "generated_at": utc_now(), "generated_by": actor,
            "causal_boundary": "变化不等于策略因果；不能排除模型换版、检索波动、竞品动作与样本噪声。"}


def _contains_secret(value, key: str = "") -> bool:
    import re
    normalized = key.lower()
    if (normalized in ("api_key", "secret", "secret_ref", "password", "authorization", "token", "token_hash")
            or normalized.endswith(("_api_key", "_secret", "_password", "_token"))):
        return True
    if isinstance(value, dict):
        return any(_contains_secret(item, str(name)) for name, item in value.items())
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    return isinstance(value, str) and bool(re.search(r"\bsk-[A-Za-z0-9_-]{12,}", value))


def release_gates(snapshot: dict) -> list[str]:
    errors = []
    latest = snapshot["waves"][-1]["metrics"]
    if not latest["quality"]["valid_samples"]:
        errors.append("无有效样本，禁止输出诊断结论")
    if latest["quality"]["pending_review_answers"]:
        errors.append(f"仍有 {latest['quality']['pending_review_answers']} 条回答待人工复核")
    if len(latest["measurement_modes"]) > 1:
        errors.append("memory/search 口径混合")
    if snapshot.get("comparison") and not snapshot["comparison"].get("comparable"):
        errors.append(snapshot["comparison"].get("reason") or "对比口径不一致")
    for opportunity in snapshot["opportunities"]:
        if opportunity["eligibility"] not in ("eligible", "client_confirmed"):
            errors.append(f"机会 {opportunity['id']} 未通过适用性审核")
    if _contains_secret(snapshot):
        errors.append("快照疑似包含密钥")
    return errors


def render_reports(snapshot: dict) -> tuple[str, str]:
    template = TEMPLATES.get_template("report.html")
    client = template.render(snapshot=snapshot, internal=False)
    internal = template.render(snapshot=snapshot, internal=True)
    return client, internal


def create_report(conn, project: dict, wave_ids: list[int], actor: int) -> dict:
    snapshot = build_snapshot(conn, project, wave_ids, actor)
    version = (one(conn, "SELECT MAX(version) AS value FROM reports WHERE project_id=?", (project["id"],))["value"] or 0) + 1
    snapshot["report_version"] = version
    snapshot["approval_status"] = "draft"
    snapshot_hash = hashlib.sha256(dumps(snapshot).encode()).hexdigest()
    snapshot["data_snapshot_hash"] = snapshot_hash
    client_html, internal_html = render_reports(snapshot)
    now = utc_now()
    report_id = conn.execute("INSERT INTO reports(client_id,project_id,wave_ids_json,data_snapshot_json,data_snapshot_hash,version,client_html,internal_html,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                             (project["client_id"], project["id"], dumps(wave_ids), dumps(snapshot),
                              snapshot_hash, version,
                              client_html, internal_html, actor, now, now)).lastrowid
    conn.execute("INSERT INTO report_events(report_id,actor,to_status,created_at) VALUES(?,?,'draft',?)", (report_id, actor, now))
    row = one(conn, "SELECT * FROM reports WHERE id=?", (report_id,))
    audit(conn, actor, project, "report", report_id, "create", None, {"version": version, "wave_ids": wave_ids})
    return row


def transition_report(conn, report: dict, new_status: str, actor: int, reason: str = "") -> dict:
    if new_status == "data_checked":
        snapshot = loads(report["data_snapshot_json"], {})
        errors = release_gates(snapshot)
        if errors:
            raise HTTPException(409, {"message": "报告发布闸门未通过", "errors": errors})
    return transition(conn, "reports", report, new_status, actor, reason)
