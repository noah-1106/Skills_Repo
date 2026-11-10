"""Derived judge lineage and delivery quality; no parallel mutable status machine."""
from __future__ import annotations

import copy
from collections import Counter

from ..db import all_rows, dumps, loads, one
from .measurement import load_run_samples


def _original_signature(protocol: dict) -> dict:
    return {key: protocol.get(key) for key in
            ("judge_mode", "judge_signature", "judge_execution", "judge_version", "use_judge")}


def judge_lineage(conn, run: dict, samples: list[dict] | None = None) -> dict:
    protocol = loads(run["snapshot_json"], {}).get("protocol") or {}
    valid_ids = [int(sample["id"]) for sample in (samples if samples is not None else load_run_samples(conn, run)[0])
                 if sample.get("valid_sample")]
    batches = all_rows(conn, "SELECT * FROM judge_batches WHERE run_id=? ORDER BY id", (run["id"],))
    batch_payload = []
    for batch in batches:
        counts = {row["status"]: row["count"] for row in conn.execute(
            "SELECT status,COUNT(*) AS count FROM judge_batch_items WHERE batch_id=? GROUP BY status", (batch["id"],))}
        engine = loads(batch["judge_engine_snapshot_json"], {})
        batch_payload.append({
            "id": batch["id"], "status": batch["status"], "scope": batch["scope"],
            "total": sum(counts.values()), "done": counts.get("done", 0), "failed": counts.get("failed", 0),
            "cancelled": counts.get("cancelled", 0),
            "judge_engine": {"id": engine.get("id"), "name": engine.get("name"),
                             "kind": engine.get("kind"), "model": engine.get("model")},
            "execution": loads(batch["execution_json"], {}), "judge_version": batch["judge_version"],
        })
    active = [item["id"] for item in batch_payload if item["status"] in ("queued", "running")]
    done = all_rows(conn, """SELECT i.answer_id,i.batch_id,b.judge_engine_snapshot_json,b.execution_json,b.judge_version
        FROM judge_batch_items i JOIN judge_batches b ON b.id=i.batch_id
        WHERE b.run_id=? AND i.status='done' ORDER BY i.answer_id,i.batch_id DESC""", (run["id"],))
    latest = {}
    for row in done:
        latest.setdefault(int(row["answer_id"]), row)
    signatures = {}
    uncovered = []
    for answer_id in valid_ids:
        row = latest.get(answer_id)
        if not row:
            uncovered.append(answer_id)
            continue
        engine = loads(row["judge_engine_snapshot_json"], {})
        signatures[dumps({
            "judge_mode": "independent",
            "judge_signature": {"id": engine.get("id"), "name": engine.get("name"), "kind": engine.get("kind"),
                                "model": engine.get("model"), "mode": engine.get("mode"),
                                "measurement_target": engine.get("measurement_target"), "role": "independent_judge"},
            "judge_execution": loads(row["execution_json"], {}),
            "judge_version": row["judge_version"], "use_judge": True,
        })] = row
    if not batches and not valid_ids:
        status = "not_applicable"
    elif not done:
        status = "original"
    elif len(valid_ids) == len(latest) and len(signatures) == 1:
        status = "consistent"
    else:
        status = "mixed"
    signature = next(iter(signatures.values()), None)
    if status == "consistent" and signature:
        effective = {
            "judge_mode": "independent",
            "judge_signature": {"id": (engine := loads(signature["judge_engine_snapshot_json"], {})).get("id"),
                                "name": engine.get("name"), "kind": engine.get("kind"), "model": engine.get("model"),
                                "mode": engine.get("mode"), "measurement_target": engine.get("measurement_target"),
                                "role": "independent_judge"},
            "judge_execution": loads(signature["execution_json"], {}),
            "judge_version": signature["judge_version"], "use_judge": True,
        }
    else:
        effective = _original_signature(protocol)
    return {
        "status": status, "covered_answers": len(set(latest) & set(valid_ids)), "valid_answers": len(valid_ids),
        "uncovered_answer_ids": uncovered, "signature_count": len(signatures), "active_batch_ids": active,
        "batches": batch_payload, "effective": effective,
        "strictly_comparable": status in ("original", "consistent") and not active,
    }


def effective_protocol(conn, run: dict, protocol: dict | None = None) -> dict:
    result = copy.deepcopy(protocol if protocol is not None else loads(run["snapshot_json"], {}).get("protocol") or {})
    lineage = judge_lineage(conn, run)
    result.update(lineage["effective"])
    result["effective_judge_status"] = lineage["status"]
    result["effective_judge_coverage"] = {"hits": lineage["covered_answers"], "n": lineage["valid_answers"]}
    result["active_judge_batch_ids"] = lineage["active_batch_ids"]
    return result


def _models(conn, run: dict, protocol: dict) -> dict:
    configured = {int(engine["id"]): engine for engine in protocol.get("engine_signature") or []}
    answer_rows = all_rows(conn, "SELECT engine_config_id,model FROM answers WHERE run_id=? AND model IS NOT NULL", (run["id"],))
    actual = {}
    for row in answer_rows:
        actual.setdefault(int(row["engine_config_id"]), set()).add(row["model"])
    answers = []
    for engine_id, engine in configured.items():
        models = sorted(actual.get(engine_id, set()))
        answers.append({"engine_config_id": engine_id, "name": engine.get("name"),
                        "configured_model": engine.get("model") or "", "actual_models": models,
                        "provider_routing_observed": any(model != engine.get("model") for model in models)})
    judge_rows = all_rows(conn, """SELECT engine_config_id,model,judge_batch_id FROM call_attempts
        WHERE run_id=? AND kind='judge' AND model IS NOT NULL ORDER BY id""", (run["id"],))
    judge_actual = {}
    for row in judge_rows:
        judge_actual.setdefault((row["engine_config_id"], row["judge_batch_id"]), set()).add(row["model"])
    judge_configurations = []
    if protocol.get("judge_signature"):
        judge_configurations.append({"engine_config_id": protocol["judge_signature"].get("id"),
                                     "name": protocol["judge_signature"].get("name"),
                                     "configured_model": protocol["judge_signature"].get("model") or "",
                                     "judge_batch_id": None})
    else:
        judge_configurations.extend({"engine_config_id": item["engine_config_id"], "name": item["name"],
                                     "configured_model": item["configured_model"], "judge_batch_id": None}
                                    for item in answers)
    lineage = judge_lineage(conn, run)
    for batch in lineage["batches"]:
        engine = batch["judge_engine"]
        judge_configurations.append({"engine_config_id": engine["id"], "name": engine["name"],
                                     "configured_model": engine["model"] or "", "judge_batch_id": batch["id"]})
    judges = []
    for item in judge_configurations:
        models = sorted(judge_actual.get((item["engine_config_id"], item["judge_batch_id"]), set()))
        judges.append({**item, "actual_models": models,
                       "provider_routing_observed": any(model != item["configured_model"] for model in models)})
    return {"answers": answers, "judges": judges}


def run_quality(conn, run: dict, *, include_protocol: bool = False) -> dict:
    samples, context = load_run_samples(conn, run)
    protocol = loads(run["snapshot_json"], {}).get("protocol") or context["protocol"]
    valid = [sample for sample in samples if sample.get("valid_sample")]
    observations = [observation for sample in valid for observation in sample.get("observations", [])]
    statuses = Counter(observation.get("judge_status") or "missing" for observation in observations)
    fallback_recommended = [observation for observation in observations
                            if observation.get("depth") == "recommended"
                            and observation.get("judge_status") in ("rules-fallback", "llm-judge-evidence-fallback")]
    provisional = [observation for observation in observations
                   if observation.get("depth") == "recommended" and observation.get("review_status") == "pending"]
    pending_answers = {sample["id"] for sample in valid
                       if any(observation.get("review_status") == "pending" for observation in sample.get("observations", []))}
    rules_answers = {sample["id"] for sample in valid
                     if any(observation.get("judge_status") == "rules-fallback" for observation in sample.get("observations", []))}
    evidence_answers = {sample["id"] for sample in valid
                        if any(observation.get("judge_status") == "llm-judge-evidence-fallback"
                               for observation in sample.get("observations", []))}
    human_revisions = one(conn, """SELECT COUNT(*) AS count FROM observations o JOIN answers a ON a.id=o.answer_id
        WHERE a.run_id=? AND o.judge_status IN ('human-review','human-arbitrated')""", (run["id"],))["count"]
    lineage = judge_lineage(conn, run, samples)
    wave = one(conn, "SELECT official_run_id FROM waves WHERE id=?", (run["wave_id"],)) or {}
    official = wave.get("official_run_id") == run["id"]
    blocking = []
    if run["status"] in ("queued", "running"):
        blocking.append("Run 尚未结束")
    if lineage["active_batch_ids"]:
        blocking.append("补判批次仍在执行")
    if lineage["status"] == "mixed":
        blocking.append("Judge 补判覆盖或配置不一致")
    if protocol.get("judge_mode") == "disabled" and lineage["status"] != "consistent":
        blocking.append("原 Run 未配置 Judge，尚未形成完整补判口径")
    if pending_answers:
        blocking.append(f"{len(pending_answers)} 条回答仍待人工复核")
    if provisional:
        blocking.append(f"{len(provisional)} 条推荐判定仍为 provisional")
    if fallback_recommended:
        blocking.append(f"{len(fallback_recommended)} 条 fallback 推荐必须人工复核")
    if valid and len(rules_answers) / len(valid) > 0.2:
        blocking.append("规则 fallback 超过有效回答的 20%")
    if not valid and run["status"] not in ("queued", "running"):
        blocking.append("没有有效样本")
    if run["status"] in ("done", "partial") and not official:
        blocking.append("尚未由管理员指定正式 Run")
    if run["status"] in ("queued", "running") or lineage["active_batch_ids"]:
        action = "wait_for_execution"
    elif run["status"] in ("failed", "partial", "cancelled") and any(sample["status"] in ("failed", "cancelled") for sample in samples):
        action = "retry_failed_samples"
    elif protocol.get("judge_mode") == "disabled" and lineage["status"] != "consistent":
        action = "create_judge_batch"
    elif lineage["status"] == "mixed":
        action = "complete_judge_coverage"
    elif pending_answers or provisional or fallback_recommended:
        action = "review_evidence"
    elif not official and run["status"] in ("done", "partial"):
        action = "select_official_run"
    elif blocking:
        action = "review_quality_limits"
    else:
        action = "ready"
    limited = bool(run["status"] == "partial" or len(valid) < 30 or any(sample.get("engine_kind") == "demo" for sample in valid))
    readiness = "not_ready" if blocking else "ready_with_limitations" if limited else "ready"
    result = {
        "execution_status": run["status"], "expected_samples": len(samples), "valid_samples": len(valid),
        "failed_samples": sum(sample["status"] == "failed" for sample in samples),
        "cancelled_samples": sum(sample["status"] == "cancelled" for sample in samples),
        "judge_mode": protocol.get("judge_mode") or "legacy", "judge_lineage": lineage["status"],
        "judge_coverage": {"hits": lineage["covered_answers"], "n": lineage["valid_answers"]},
        "active_judge_batches": lineage["active_batch_ids"], "judge_batches": lineage["batches"],
        "rules_fallback_answers": len(rules_answers), "evidence_fallback_answers": len(evidence_answers),
        "fallback_recommended_pending": sum(observation.get("review_status") == "pending" for observation in fallback_recommended),
        "pending_review_answers": len(pending_answers), "provisional_recommendations": len(provisional),
        "human_revisions": human_revisions, "judge_status_counts": dict(statuses),
        "models": _models(conn, run, protocol), "official_run": official,
        "delivery_readiness": readiness, "blocking_reasons": blocking,
        "next_action": {"kind": action, "run_id": run["id"]},
    }
    if include_protocol:
        result["effective_protocol"] = effective_protocol(conn, run, protocol)
    return result
