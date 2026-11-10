"""Judge-only batches over immutable answers; never re-run answer or search calls."""
from __future__ import annotations

import hashlib

from fastapi import HTTPException

from ..db import all_rows, dumps, loads, one, transaction, utc_now
from ..engine.judge import JUDGE_VERSION, fallback_observations, judge_answer
from ..providers import ProviderError, build_provider
from ..security import SecretStore, audit
from .budgets import authorize_budget, release as release_budget, reserve, scale_estimate
from .costs import JUDGE_INPUT_TOKENS, quote, rule_for
from .execution import resolve_execution
from .measurement import (_answer_context, _engine_slot, _insert_discovered, _record_operations,
                          _store_observations, engine_execution, engine_public)

ACTIVE_STATUSES = ("queued", "running")


def estimate_judge_batch(engine: dict, execution: dict, count: int, max_safe_retries: int = 2) -> dict:
    rule = rule_for(engine)
    output = int(execution.get("max_tokens") or rule.get("estimated_output_tokens") or 1800)
    base_usage = {"prompt_tokens": count * JUDGE_INPUT_TOKENS, "completion_tokens": count * output}
    max_usage = {"prompt_tokens": base_usage["prompt_tokens"] * (1 + max_safe_retries),
                 "completion_tokens": base_usage["completion_tokens"] * (1 + max_safe_retries)}
    base, currency, missing = quote(rule, "judge", base_usage)
    maximum, _, max_missing = quote(rule, "judge", max_usage)
    unknown = sorted({*missing, *max_missing})
    return {
        "answer_calls": 0, "search_calls": 0, "judge_calls": count,
        "total_external_calls": count, "max_external_calls": count * (1 + max_safe_retries),
        "estimated_input_tokens": base_usage["prompt_tokens"],
        "estimated_output_tokens": base_usage["completion_tokens"],
        "max_estimated_input_tokens": max_usage["prompt_tokens"],
        "max_estimated_output_tokens": max_usage["completion_tokens"],
        "estimated_cost": round(base, 6) if base is not None else None,
        "max_estimated_cost": round(maximum, 6) if maximum is not None else None,
        "known_cost": round(base or 0, 6), "currency": currency,
        "cost_unknown": bool(unknown), "unknown_components": [f"{engine.get('name')}:{item}" for item in unknown],
        "mixed_currencies": False,
        "note": "仅复用已有原文执行 Judge；回答与 Search 调用为 0。token 和金额为启发式预估，不是厂商账单。",
    }


def batch_public(conn, batch: dict, *, include_items: bool = False, role: str = "admin") -> dict:
    result = {key: value for key, value in batch.items()
              if key not in ("judge_engine_snapshot_json", "execution_json", "estimate_json")}
    result["judge_engine"] = engine_public(loads(batch["judge_engine_snapshot_json"], {}))
    result["execution"] = loads(batch["execution_json"], {})
    result["estimate"] = loads(batch["estimate_json"], {})
    if role in ("reviewer", "viewer"):
        for key in ("estimated_cost", "max_estimated_cost", "known_cost", "currency", "unknown_components"):
            result["estimate"].pop(key, None)
        result.pop("budget_confirmation_reason", None)
    result["progress"] = {row["status"]: row["count"] for row in conn.execute(
        "SELECT status,COUNT(*) AS count FROM judge_batch_items WHERE batch_id=? GROUP BY status", (batch["id"],))}
    result["progress"]["total"] = sum(value for key, value in result["progress"].items() if key != "total")
    if include_items:
        result["items"] = all_rows(conn, """SELECT i.id,i.answer_id,i.status,i.attempt_no,i.error_type,
            i.error_detail,i.outcome_unknown,i.created_at,i.started_at,i.finished_at
            FROM judge_batch_items i WHERE i.batch_id=? ORDER BY i.answer_id""", (batch["id"],))
    return result


def _eligibility(conn, run: dict, answer: dict) -> str:
    if answer["status"] != "succeeded" or not answer.get("valid_sample"):
        return "answer_not_valid"
    if not answer.get("content_retained", 1):
        return "raw_purged"
    raw = answer.get("raw_text") or ""
    if not raw:
        return "raw_missing"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if not answer.get("raw_text_sha256") or answer["raw_text_sha256"] != digest:
        return "raw_hash_mismatch"
    snapshot = loads(run["snapshot_json"], {})
    protocol = snapshot.get("protocol") or snapshot
    if protocol.get("measurement_target") == "consumer_web":
        collection = one(conn, "SELECT status FROM web_collections WHERE answer_id=?", (answer["id"],))
        if not collection or collection["status"] != "completed":
            return "collection_evidence_incomplete"
    return ""


def create_judge_batch(project: dict, actor: int, run: dict, payload: dict) -> dict:
    with transaction() as conn:
        if run["status"] in ACTIVE_STATUSES:
            raise HTTPException(409, "原 Run 尚未结束，不能创建补判批次")
        requested_ids = payload.get("answer_ids")
        scope = "selected" if requested_ids is not None else "all_eligible"
        if requested_ids is not None and not requested_ids:
            raise HTTPException(400, "answer_ids 不能为空；全量补判请省略该字段")
        answers = all_rows(conn, "SELECT * FROM answers WHERE run_id=? ORDER BY id", (run["id"],))
        by_id = {int(answer["id"]): answer for answer in answers}
        if scope == "selected":
            missing = sorted(set(requested_ids) - set(by_id))
            if missing:
                raise HTTPException(404, f"Answer 不属于当前 Run：{missing}")
            candidates = [by_id[int(answer_id)] for answer_id in sorted(set(requested_ids))]
        else:
            candidates = answers
        eligible, excluded = [], []
        for answer in candidates:
            reason = _eligibility(conn, run, answer)
            if reason:
                excluded.append({"answer_id": answer["id"], "reason": reason})
            else:
                eligible.append(answer)
        if scope == "selected" and excluded:
            raise HTTPException(409, detail={"code": "judge_batch_answers_ineligible", "excluded": excluded})
        if not eligible:
            raise HTTPException(409, detail={"code": "judge_batch_answers_ineligible", "excluded": excluded})
        answer_ids = [int(answer["id"]) for answer in eligible]
        marks = ",".join("?" for _ in answer_ids)
        conflicts = all_rows(conn, f"""SELECT i.answer_id FROM judge_batch_items i
            JOIN judge_batches b ON b.id=i.batch_id
            WHERE i.answer_id IN ({marks}) AND i.status IN ('queued','running')
              AND b.status IN ('queued','running') AND b.cancel_requested=0""", answer_ids)
        if conflicts:
            raise HTTPException(409, f"这些 Answer 已有活跃补判批次：{[row['answer_id'] for row in conflicts]}")
        judge_engine = one(conn, """SELECT * FROM engine_configs
            WHERE id=? AND project_id=? AND client_id=? AND enabled=1 AND kind!='manual_web'""",
                           (payload["judge_engine_id"], project["id"], project["client_id"]))
        if not judge_engine:
            raise HTTPException(409, "必须选择当前项目已启用的 Provider Judge 引擎")
        snapshot = loads(run["snapshot_json"], {})
        protocol = snapshot.get("protocol") or snapshot
        answer_kinds = {item.get("kind") for item in protocol.get("engine_signature") or []}
        if protocol.get("measurement_target") == "provider_api":
            if "demo" in answer_kinds and judge_engine["kind"] != "demo":
                raise HTTPException(409, "Demo 回答不能使用真实 Judge 补判")
            if any(kind != "demo" for kind in answer_kinds) and judge_engine["kind"] == "demo":
                raise HTTPException(409, "真实回答不能使用 Demo Judge 补判")
        execution = resolve_execution(judge_engine, "judge", payload.get("judge_overrides") or {})
        max_safe_retries = int(protocol.get("max_safe_retries", 2))
        estimate = estimate_judge_batch(judge_engine, execution, len(eligible), max_safe_retries)
        if judge_engine["kind"] != "demo" and not payload.get("confirm"):
            raise HTTPException(409, detail={"code": "judge_batch_confirmation_required",
                                            "message": "补判会产生真实 Judge 调用；不会重新请求回答或 Search，请确认预估后重试",
                                            "estimate": estimate, "eligible_answers": len(eligible), "excluded": excluded})
        reason = payload.get("budget_confirmation_reason") or ""
        decision = authorize_budget(conn, project, estimate, actor=actor, confirmation_reason=reason)
        now = utc_now()
        batch_id = conn.execute("""INSERT INTO judge_batches(
            client_id,project_id,run_id,scope,status,judge_engine_snapshot_json,execution_json,judge_version,
            estimate_json,max_safe_retries,budget_confirmation_reason,created_by,created_at)
            VALUES(?,?,?,?, 'queued',?,?,?,?,?,?,?,?)""",
                                (project["client_id"], project["id"], run["id"], scope,
                                 dumps(engine_execution(judge_engine)), dumps(execution), JUDGE_VERSION,
                                 dumps(estimate), max_safe_retries, decision.get("override_reason") or "", actor, now)).lastrowid
        conn.executemany("""INSERT INTO judge_batch_items(client_id,project_id,batch_id,answer_id,status,created_at)
                            VALUES(?,?,?,?, 'queued',?)""",
                         [(project["client_id"], project["id"], batch_id, answer_id, now) for answer_id in answer_ids])
        reserve(conn, project, decision, operation_id=f"judge-batch:{batch_id}", actor=actor)
        audit(conn, actor, project, "judge_batch", batch_id, "create", None,
              {"run_id": run["id"], "answer_ids": answer_ids, "excluded": excluded,
               "judge_engine_id": judge_engine["id"], "execution": execution})
        batch = one(conn, "SELECT * FROM judge_batches WHERE id=?", (batch_id,))
        result = batch_public(conn, batch, include_items=True)
        result["excluded"] = excluded
        return result


def list_judge_batches(conn, run_id: int, role: str = "admin") -> list[dict]:
    return [batch_public(conn, row, role=role) for row in all_rows(
        conn, "SELECT * FROM judge_batches WHERE run_id=? ORDER BY id DESC", (run_id,))]


def claim_judge_item() -> dict | None:
    with transaction() as conn:
        row = one(conn, """SELECT i.id,i.batch_id FROM judge_batch_items i
            JOIN judge_batches b ON b.id=i.batch_id
            WHERE i.status='queued' AND b.status IN ('queued','running') AND b.cancel_requested=0
            ORDER BY i.id LIMIT 1""")
        if not row:
            return None
        now = utc_now()
        conn.execute("""UPDATE judge_batch_items SET status='running',attempt_no=attempt_no+1,
                        started_at=COALESCE(started_at,?),finished_at=NULL,error_type=NULL,error_detail=NULL WHERE id=?""",
                     (now, row["id"]))
        conn.execute("UPDATE judge_batches SET status='running',started_at=COALESCE(started_at,?) WHERE id=?",
                     (now, row["batch_id"]))
        return row


def _finalize_judge_batch(conn, batch_id: int) -> None:
    remaining = one(conn, "SELECT COUNT(*) AS count FROM judge_batch_items WHERE batch_id=? AND status IN ('queued','running')",
                    (batch_id,))["count"]
    if remaining:
        return
    counts = {row["status"]: row["count"] for row in conn.execute(
        "SELECT status,COUNT(*) AS count FROM judge_batch_items WHERE batch_id=? GROUP BY status", (batch_id,))}
    batch = one(conn, "SELECT * FROM judge_batches WHERE id=?", (batch_id,))
    if batch["cancel_requested"]:
        status = "cancelled"
    elif counts.get("done", 0) == 0:
        status = "failed"
    elif counts.get("failed", 0) or counts.get("cancelled", 0):
        status = "partial"
    else:
        status = "done"
    conn.execute("UPDATE judge_batches SET status=?,finished_at=? WHERE id=?", (status, utc_now(), batch_id))
    release_budget(conn=conn, operation_id=f"judge-batch:{batch_id}")


def process_judge_item(item_id: int) -> None:
    with transaction() as conn:
        item = one(conn, "SELECT * FROM judge_batch_items WHERE id=?", (item_id,))
        if not item or item["status"] != "running":
            return
        batch = one(conn, "SELECT * FROM judge_batches WHERE id=?", (item["batch_id"],))
        context = _answer_context(conn, item["answer_id"])
        engine = loads(batch["judge_engine_snapshot_json"], {})
        execution = loads(batch["execution_json"], {})
        citations = all_rows(conn, "SELECT raw_url AS url,title,domain FROM citations WHERE answer_id=?", (item["answer_id"],))
    if not context or not context.get("raw_text"):
        with transaction() as conn:
            conn.execute("""UPDATE judge_batch_items SET status='failed',error_type='raw_missing',
                            error_detail='原文不可用，未执行补判',finished_at=? WHERE id=?""", (utc_now(), item_id))
            _finalize_judge_batch(conn, item["batch_id"])
        return
    entities = context["entities"]
    try:
        if engine["kind"] == "demo":
            observations = fallback_observations(context["raw_text"], entities, demo=True)
            operations = [{"kind": "judge", "status": "succeeded", "model": "geopulse-demo-judge",
                           "usage": {}, "request_id": f"demo-judge-batch-{item['batch_id']}-{item_id}",
                           "latency_ms": 0, "request_params": execution, "response_meta": {}}]
            for observation in observations:
                observation["judge_meta"] = {"prompt_version": JUDGE_VERSION, "model": "geopulse-demo-judge"}
            discovered = []
        else:
            provider = build_provider(engine, SecretStore().get(engine.get("secret_ref", "")),
                                      [entity["name"] for entity in sorted(entities, key=lambda row: row["role"] != "primary")])
            with _engine_slot(engine):
                observations, discovered, judged = judge_answer(provider, context["raw_text"], entities, execution, citations)
            operations = judged.operations
        for observation in observations:
            observation["judge_meta"] = {**(observation.get("judge_meta") or {}),
                                         "configured_model": engine.get("model") or ""}
        with transaction() as conn:
            current = one(conn, "SELECT status FROM judge_batch_items WHERE id=?", (item_id,))
            batch = one(conn, "SELECT cancel_requested FROM judge_batches WHERE id=?", (item["batch_id"],))
            if not current or current["status"] != "running":
                return
            _record_operations(conn, context, operations, engine=engine, judge_batch_id=item["batch_id"])
            if batch["cancel_requested"]:
                conn.execute("UPDATE judge_batch_items SET status='cancelled',finished_at=? WHERE id=?", (utc_now(), item_id))
            else:
                _store_observations(conn, context, observations, append=True,
                                    judge_batch_id=item["batch_id"], judge_batch_item_id=item_id)
                _insert_discovered(conn, context, discovered)
                conn.execute("UPDATE judge_batch_items SET status='done',finished_at=? WHERE id=?", (utc_now(), item_id))
            _finalize_judge_batch(conn, item["batch_id"])
    except Exception as error:
        kind = error.kind if isinstance(error, ProviderError) else "judge_invalid"
        unknown = bool(not isinstance(error, ProviderError) or error.outcome_unknown)
        with transaction() as conn:
            _record_operations(conn, context, error.operations if isinstance(error, ProviderError) else [],
                               {"kind": "judge", "error_type": kind, "error_detail": str(error)[:1000]},
                               engine=engine, judge_batch_id=item["batch_id"])
            current = one(conn, "SELECT attempt_no FROM judge_batch_items WHERE id=?", (item_id,))
            retry = (isinstance(error, ProviderError) and error.retryable and not unknown
                     and current["attempt_no"] <= int(batch["max_safe_retries"]))
            conn.execute("""UPDATE judge_batch_items SET status=?,error_type=?,error_detail=?,outcome_unknown=?,
                            finished_at=? WHERE id=?""",
                         ("queued" if retry else "failed", kind, str(error)[:1000], int(unknown),
                          None if retry else utc_now(), item_id))
            _finalize_judge_batch(conn, item["batch_id"])


def recover_judge_batches() -> None:
    with transaction() as conn:
        # A running item may already have reached the provider. Never replay that
        # uncertain external call automatically after a process restart.
        conn.execute("""UPDATE judge_batch_items SET status='failed',error_type='interrupted_unknown',
                        error_detail='进程恢复时无法确认在途 Judge 是否已计费或返回；不会自动重放',
                        outcome_unknown=1,finished_at=? WHERE status='running' AND batch_id IN
                        (SELECT id FROM judge_batches WHERE cancel_requested=0)""", (utc_now(),))
        conn.execute("""UPDATE judge_batch_items SET status='cancelled',finished_at=? WHERE status IN ('queued','running')
                        AND batch_id IN (SELECT id FROM judge_batches WHERE cancel_requested=1)""", (utc_now(),))
        batches = all_rows(conn, "SELECT id FROM judge_batches WHERE status IN ('queued','running')")
        for batch in batches:
            _finalize_judge_batch(conn, batch["id"])


def cancel_judge_batch(project: dict, actor: int, batch: dict) -> dict:
    with transaction() as conn:
        if batch["status"] not in ACTIVE_STATUSES:
            raise HTTPException(409, "补判批次已结束")
        conn.execute("UPDATE judge_batches SET cancel_requested=1 WHERE id=?", (batch["id"],))
        conn.execute("""UPDATE judge_batch_items SET status='cancelled',finished_at=?
                        WHERE batch_id=? AND status='queued'""", (utc_now(), batch["id"]))
        _finalize_judge_batch(conn, batch["id"])
        audit(conn, actor, project, "judge_batch", batch["id"], "cancel", None, None)
        return batch_public(conn, one(conn, "SELECT * FROM judge_batches WHERE id=?", (batch["id"],)), include_items=True)


def retry_judge_batch(project: dict, actor: int, batch: dict, payload: dict) -> dict:
    with transaction() as conn:
        if batch["status"] in ACTIVE_STATUSES:
            raise HTTPException(409, "活跃补判批次不能重试")
        failed = all_rows(conn, "SELECT * FROM judge_batch_items WHERE batch_id=? AND status='failed' AND outcome_unknown=0",
                          (batch["id"],))
        if not failed:
            raise HTTPException(409, "没有结果明确且可安全重试的失败补判项")
        engine = loads(batch["judge_engine_snapshot_json"], {})
        estimate = loads(batch["estimate_json"], {})
        total = int(estimate.get("judge_calls") or 0)
        scaled = scale_estimate(estimate, len(failed) / total) if total else estimate
        if engine["kind"] != "demo" and not payload.get("confirm"):
            raise HTTPException(409, detail={"code": "judge_batch_confirmation_required",
                                            "message": "重试会再次产生真实 Judge 调用，请确认预估",
                                            "estimate": scaled, "retry_items": len(failed)})
        decision = authorize_budget(conn, project, scaled, actor=actor,
                                    confirmation_reason=payload.get("budget_confirmation_reason") or "")
        ids = [item["id"] for item in failed]
        marks = ",".join("?" for _ in ids)
        conn.execute(f"""UPDATE judge_batch_items SET status='queued',error_type=NULL,error_detail=NULL,
                        finished_at=NULL WHERE id IN ({marks})""", ids)
        conn.execute("""UPDATE judge_batches SET status='queued',cancel_requested=0,finished_at=NULL,
                        budget_confirmation_reason=? WHERE id=?""",
                     (decision.get("override_reason") or "", batch["id"]))
        reserve(conn, project, decision, operation_id=f"judge-batch:{batch['id']}", actor=actor)
        audit(conn, actor, project, "judge_batch", batch["id"], "retry", None, {"items": ids})
        return batch_public(conn, one(conn, "SELECT * FROM judge_batches WHERE id=?", (batch["id"],)), include_items=True)
