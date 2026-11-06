"""Opportunity/action/external-event workflow routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..db import all_rows, connect, dumps, loads, one, utc_now
from ..security import audit, project_context, require_admin
from ..services import opportunities
from ..services.state import scoped_object, transition
from .schemas import ActionIn, ActionStatusIn, EventIn, OpportunityReviewIn, StatusIn

router = APIRouter(prefix="/api/projects/{project_id}", tags=["workflow"])


def opportunity_public(row: dict) -> dict:
    result = dict(row)
    result["evidence"] = loads(result.pop("evidence_json"), {})
    result["score_detail"] = loads(result.pop("score_json"), {})
    return result


@router.post("/waves/{wave_id}/opportunities/generate")
def generate(project_id: int, wave_id: int, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        wave = scoped_object(conn, "waves", wave_id, context["project"])
        rows = opportunities.generate_opportunities(conn, wave, context["user"]["id"])
        conn.commit()
        return {"items": [opportunity_public(row) for row in rows], "count": len(rows)}


@router.get("/opportunities")
def list_opportunities(project_id: int, request: Request, status: str = ""):
    context = project_context(request, project_id)
    with connect() as conn:
        rows = all_rows(conn, "SELECT o.*,p.text AS prompt_text,p.dimension,w.label AS wave_label FROM opportunities o JOIN prompt_items p ON p.id=o.prompt_item_id JOIN waves w ON w.id=o.wave_id WHERE o.project_id=?" + (" AND o.status=?" if status else "") + " ORDER BY CASE WHEN o.score IS NULL THEN 0 ELSE o.score END DESC,o.id DESC",
                        (project_id, status) if status else (project_id,))
        return {"items": [opportunity_public(row) for row in rows]}


@router.post("/opportunities/{opportunity_id}/review")
def review(project_id: int, opportunity_id: int, payload: OpportunityReviewIn, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        opportunity = scoped_object(conn, "opportunities", opportunity_id, context["project"])
        row = opportunities.review_opportunity(conn, opportunity, context["user"]["id"], payload.model_dump(), context["project"])
        conn.commit()
        return opportunity_public(row)


@router.post("/opportunities/{opportunity_id}/status")
def close_opportunity(project_id: int, opportunity_id: int, payload: StatusIn, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        opportunity = scoped_object(conn, "opportunities", opportunity_id, context["project"])
        if payload.status != "closed":
            raise HTTPException(400, "该接口仅用于关闭机会")
        if not payload.reason.strip():
            raise HTTPException(400, "关闭机会必须记录复测改善证据或不再投入的理由")
        row = transition(conn, "opportunities", opportunity, "closed", context["user"]["id"], payload.reason,
                         {"close_reason": payload.reason})
        conn.commit()
        return opportunity_public(row)


@router.post("/opportunities/{opportunity_id}/actions")
def create_action(project_id: int, opportunity_id: int, payload: ActionIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        opportunity = scoped_object(conn, "opportunities", opportunity_id, context["project"])
        row = opportunities.create_action(conn, opportunity, context["user"]["id"], payload.model_dump())
        conn.commit()
        return row


@router.get("/actions")
def list_actions(project_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        return {"items": all_rows(conn, "SELECT a.*,o.gap_type,o.eligibility,o.wave_id AS opportunity_wave_id FROM actions a JOIN opportunities o ON o.id=a.opportunity_id WHERE a.project_id=? ORDER BY a.updated_at DESC", (project_id,))}


@router.post("/actions/{action_id}/status")
def action_status(project_id: int, action_id: int, payload: ActionStatusIn, request: Request):
    minimum = "admin" if payload.status in ("approved", "published", "verified", "not_effective") else "analyst"
    context = project_context(request, project_id, minimum)
    with connect() as conn:
        action = scoped_object(conn, "actions", action_id, context["project"])
        if payload.target_wave_id:
            scoped_object(conn, "waves", payload.target_wave_id, context["project"])
        row = opportunities.transition_action(conn, action, payload.status, context["user"]["id"], payload.model_dump())
        conn.commit()
        return row


@router.get("/events")
def list_events(project_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        return {"items": all_rows(conn, "SELECT * FROM external_events WHERE project_id=? ORDER BY event_at DESC", (project_id,))}


@router.post("/events")
def create_event(project_id: int, payload: EventIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        event_id = conn.execute("INSERT INTO external_events(client_id,project_id,event_at,kind,description,source,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
                                (context["project"]["client_id"], project_id, payload.event_at, payload.kind,
                                 payload.description, payload.source, context["user"]["id"], utc_now())).lastrowid
        row = one(conn, "SELECT * FROM external_events WHERE id=?", (event_id,))
        audit(conn, context["user"]["id"], context["project"], "external_event", event_id, "create", None, row)
        conn.commit()
        return row
