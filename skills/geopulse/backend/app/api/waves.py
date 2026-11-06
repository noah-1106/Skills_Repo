"""Wave execution, evidence review and strict comparison routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..db import all_rows, connect, dumps, loads, one, utc_now
from ..engine.compare import compare_metrics
from ..engine.metrics import calculate_metrics
from ..security import audit, project_context, require_admin
from ..services.measurement import (create_run, create_wave, engine_public, estimate_wave, load_run_samples,
                                    run_progress, _finalize_run)
from ..services.reporting import wave_metrics
from ..services.state import scoped_object, transition
from .schemas import ObservationRevisionIn, StatusIn, WaveIn

router = APIRouter(prefix="/api/projects/{project_id}", tags=["waves"])


def wave_public(conn, wave: dict) -> dict:
    result = dict(wave)
    result["protocol"] = loads(result.pop("protocol_json"), {})
    result["stats"] = loads(result.pop("stats_json"), {})
    result["estimate"] = estimate_wave(conn, wave)
    result["runs"] = all_rows(conn, "SELECT id,attempt_no,status,started_at,finished_at,error FROM runs WHERE wave_id=? ORDER BY attempt_no DESC", (wave["id"],))
    return result


@router.get("/waves")
def list_waves(project_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        return {"items": [wave_public(conn, row) for row in all_rows(conn, "SELECT * FROM waves WHERE project_id=? ORDER BY id DESC", (project_id,))]}


@router.post("/waves")
def new_wave(project_id: int, payload: WaveIn, request: Request):
    context = project_context(request, project_id, "analyst")
    wave = create_wave(context["project"], context["user"]["id"], payload.model_dump())
    with connect() as conn:
        return wave_public(conn, wave)


@router.get("/waves/{wave_id}")
def get_wave(project_id: int, wave_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        return wave_public(conn, scoped_object(conn, "waves", wave_id, context["project"]))


@router.post("/waves/{wave_id}/runs")
def new_run(project_id: int, wave_id: int, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        wave = scoped_object(conn, "waves", wave_id, context["project"])
    run = create_run(context["project"], wave, context["user"]["id"])
    return {"run": run, "progress": {"total": 0, "finished": 0, "progress": 0}}


@router.post("/waves/{wave_id}/official")
def official_run(project_id: int, wave_id: int, payload: dict, request: Request):
    context = require_admin(request, project_id)
    run_id = int(payload.get("run_id") or 0)
    with connect() as conn:
        wave = scoped_object(conn, "waves", wave_id, context["project"])
        run = scoped_object(conn, "runs", run_id, context["project"])
        if run["wave_id"] != wave_id:
            raise HTTPException(409, "run 不属于该 wave")
        if run["status"] not in ("done", "partial"):
            raise HTTPException(409, "只有完成或部分完成的 run 可被指定；部分完成会在对比时检查完整度")
        conn.execute("UPDATE waves SET official_run_id=? WHERE id=?", (run_id, wave_id))
        audit(conn, context["user"]["id"], context["project"], "wave", wave_id, "official_run",
              wave["official_run_id"], run_id)
        conn.commit()
    return {"wave_id": wave_id, "official_run_id": run_id}


@router.post("/waves/{wave_id}/status")
def wave_status(project_id: int, wave_id: int, payload: StatusIn, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        wave = scoped_object(conn, "waves", wave_id, context["project"])
        if payload.status not in ("analyzed", "closed"):
            raise HTTPException(400, "Wave 只能人工标记 analyzed 或 closed")
        row = transition(conn, "waves", wave, payload.status, context["user"]["id"], payload.reason)
        conn.commit()
        return row


@router.get("/runs/{run_id}")
def get_run(project_id: int, run_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        run = scoped_object(conn, "runs", run_id, context["project"])
        result = dict(run)
        result["snapshot"] = loads(result.pop("snapshot_json"), {})
        result["progress"] = run_progress(conn, run_id)
        return result


@router.post("/runs/{run_id}/cancel")
def cancel_run(project_id: int, run_id: int, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        run = scoped_object(conn, "runs", run_id, context["project"])
        if run["status"] in ("done", "failed", "cancelled"):
            raise HTTPException(409, "该 run 已结束")
        conn.execute("UPDATE runs SET cancel_requested=1 WHERE id=?", (run_id,))
        conn.execute("UPDATE answers SET status='cancelled',completed_at=? WHERE run_id=? AND status='queued'", (utc_now(), run_id))
        remaining = one(conn, "SELECT COUNT(*) AS count FROM answers WHERE run_id=? AND status IN ('running','judging')", (run_id,))["count"]
        if not remaining:
            _finalize_run(conn, run_id)
        audit(conn, context["user"]["id"], context["project"], "run", run_id, "cancel", None, None)
        conn.commit()
    return {"cancel_requested": True}


@router.post("/runs/{run_id}/retry")
def retry_run(project_id: int, run_id: int, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        run = scoped_object(conn, "runs", run_id, context["project"])
        count = one(conn, "SELECT COUNT(*) AS count FROM answers WHERE run_id=? AND status IN ('failed','cancelled')", (run_id,))["count"]
        if not count:
            raise HTTPException(409, "没有可重试的失败样本")
        conn.execute("UPDATE answers SET status='queued',error_type=NULL,error_detail=NULL WHERE run_id=? AND status IN ('failed','cancelled')", (run_id,))
        conn.execute("UPDATE runs SET status='queued',cancel_requested=0,finished_at=NULL WHERE id=?", (run_id,))
        conn.execute("UPDATE waves SET status='running' WHERE id=?", (run["wave_id"],))
        audit(conn, context["user"]["id"], context["project"], "run", run_id, "manual_retry", None, {"samples": count})
        conn.commit()
    return {"queued": count, "note": "超时等结果不明的调用已由管理员确认重试"}


@router.get("/runs/{run_id}/metrics")
def metrics(project_id: int, run_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        run = scoped_object(conn, "runs", run_id, context["project"])
        wave = scoped_object(conn, "waves", run["wave_id"], context["project"])
        samples, run_context = load_run_samples(conn, run)
        result = calculate_metrics(samples, run_context["primary_id"], loads(wave["stats_json"], {}))
        result.pop("pairs", None)
        result["progress"] = run_progress(conn, run_id)
        return result


@router.get("/runs/{run_id}/answers")
def answers(project_id: int, run_id: int, request: Request, status: str = "", review: str = "",
            limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    context = project_context(request, project_id)
    with connect() as conn:
        scoped_object(conn, "runs", run_id, context["project"])
        clauses, args = ["a.run_id=?"], [run_id]
        if status:
            clauses.append("a.status=?")
            args.append(status)
        rows = all_rows(conn, "SELECT a.id,a.run_id,a.prompt_item_id,a.engine_config_id,a.round_no,a.status,a.error_type,a.error_detail,a.model,a.created_at,a.completed_at,substr(a.raw_text,1,600) AS raw_text,p.text AS prompt_text,p.dimension,e.name AS engine_name,e.mode AS engine_mode FROM answers a JOIN prompt_items p ON p.id=a.prompt_item_id JOIN engine_configs e ON e.id=a.engine_config_id WHERE " + " AND ".join(clauses) + " ORDER BY a.id DESC LIMIT ? OFFSET ?", [*args, limit, offset])
        for row in rows:
            if context["role"] in ("reviewer", "viewer"):
                row["raw_text"] = None
                row["error_detail"] = None
            observations = all_rows(conn, "SELECT o.*,b.name,b.role FROM observations o JOIN brand_entities b ON b.id=o.brand_entity_id WHERE o.answer_id=? ORDER BY b.name,o.revision DESC", (row["id"],))
            latest = {}
            for observation in observations:
                if observation["brand_entity_id"] in latest:
                    continue
                observation["citation_urls"] = loads(observation.pop("citation_urls_json"), [])
                observation["judge_meta"] = loads(observation.pop("judge_meta_json"), {})
                observation["discovered"] = loads(observation.pop("discovered_json"), [])
                latest[observation["brand_entity_id"]] = observation
            row["observations"] = list(latest.values())
        if review == "pending":
            rows = [row for row in rows if any(obs["review_status"] == "pending" for obs in row["observations"])]
        total = one(conn, "SELECT COUNT(*) AS count FROM answers WHERE run_id=?", (run_id,))["count"]
        return {"items": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/answers/{answer_id}")
def answer_detail(project_id: int, answer_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        answer = scoped_object(conn, "answers", answer_id, context["project"])
        metadata = one(conn, "SELECT p.text AS prompt_text,e.name AS engine_name,e.mode AS engine_mode FROM prompt_items p,engine_configs e WHERE p.id=? AND e.id=?", (answer["prompt_item_id"], answer["engine_config_id"]))
        answer.update(metadata or {})
        answer["usage"] = loads(answer.pop("usage_json"), {})
        if context["role"] in ("reviewer", "viewer"):
            answer["raw_text"] = None
            answer["error_detail"] = None
        observations = all_rows(conn, "SELECT o.*,b.name,b.role,b.entity_card_json FROM observations o JOIN brand_entities b ON b.id=o.brand_entity_id WHERE o.answer_id=? ORDER BY o.brand_entity_id,o.revision DESC", (answer_id,))
        for observation in observations:
            observation["citation_urls"] = loads(observation.pop("citation_urls_json"), [])
            observation["judge_meta"] = loads(observation.pop("judge_meta_json"), {})
            observation["discovered"] = loads(observation.pop("discovered_json"), [])
            observation["entity_card"] = loads(observation.pop("entity_card_json"), {})
        answer["observations"] = observations
        answer["citations"] = all_rows(conn, "SELECT * FROM citations WHERE answer_id=?", (answer_id,))
        attempts = all_rows(conn, "SELECT id,kind,attempt_no,status,request_id,model,latency_ms,usage_json,cost,error_type,error_detail,created_at FROM call_attempts WHERE answer_id=? ORDER BY id", (answer_id,))
        for attempt in attempts:
            attempt["usage"] = loads(attempt.pop("usage_json"), {})
            if context["role"] in ("reviewer", "viewer"):
                attempt.pop("cost", None)
                attempt["error_detail"] = None
        answer["call_attempts"] = attempts
        return answer


@router.post("/answers/{answer_id}/observations/{observation_id}/revisions")
def revise_observation(project_id: int, answer_id: int, observation_id: int,
                       payload: ObservationRevisionIn, request: Request):
    minimum = "admin" if payload.arbitrate else "analyst"
    context = project_context(request, project_id, minimum)
    with connect() as conn:
        answer = scoped_object(conn, "answers", answer_id, context["project"])
        original = scoped_object(conn, "observations", observation_id, context["project"])
        if original["answer_id"] != answer_id:
            raise HTTPException(409, "判定不属于该回答")
        if payload.mentioned and payload.entity_status == "confirmed" and (not payload.evidence or payload.evidence not in (answer["raw_text"] or "")):
            raise HTTPException(400, "有效提及的证据必须逐字来自原文")
        if payload.sentiment == "negative" and payload.depth == "recommended":
            raise HTTPException(400, "负面或劝退不能人工标为推荐")
        revision = (one(conn, "SELECT MAX(revision) AS value FROM observations WHERE answer_id=? AND brand_entity_id=?",
                        (answer_id, original["brand_entity_id"]))["value"] or 0) + 1
        status = "confirmed" if payload.arbitrate else "pending"
        new_id = conn.execute("INSERT INTO observations(client_id,project_id,answer_id,brand_entity_id,revision,entity_status,mentioned,depth,sentiment,top_choice,evidence,citation_urls_json,discovered_json,judge_status,judge_meta_json,review_status,review_reason,reviewer_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (context["project"]["client_id"], project_id, answer_id, original["brand_entity_id"], revision,
                               payload.entity_status, int(payload.mentioned), payload.depth, payload.sentiment,
                               int(payload.top_choice and payload.depth == "recommended"), payload.evidence,
                               original["citation_urls_json"], original["discovered_json"],
                               "human-arbitrated" if payload.arbitrate else "human-review", original["judge_meta_json"],
                               status, payload.reason, context["user"]["id"], utc_now())).lastrowid
        audit(conn, context["user"]["id"], context["project"], "observation", observation_id, "revision",
              original, {"new_id": new_id, **payload.model_dump()})
        conn.commit()
        return one(conn, "SELECT * FROM observations WHERE id=?", (new_id,))


@router.get("/compare")
def compare(project_id: int, baseline_wave: int, current_wave: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        baseline = scoped_object(conn, "waves", baseline_wave, context["project"])
        current = scoped_object(conn, "waves", current_wave, context["project"])
        before, before_protocol, _ = wave_metrics(conn, baseline)
        after, after_protocol, _ = wave_metrics(conn, current)
        threshold = float(loads(current["stats_json"], {}).get("min_pair_completeness", 0.9))
        return compare_metrics(before, after, before_protocol, after_protocol, threshold)
