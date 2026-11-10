"""Opportunity/action/external-event workflow routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..db import all_rows, connect, dumps, loads, one, utc_now
from ..security import audit, project_context, require_admin
from ..services import interventions, opportunities, remeasurements
from ..services.state import scoped_object, transition
from .schemas import (ActionIn, ActionStatusIn, AssessmentIn, AssetIn, BriefIn, EventIn,
                      OpportunityReviewIn, PublicationIn, RemeasurementsIn, StatusIn)

router = APIRouter(prefix="/api/projects/{project_id}", tags=["workflow"])


def opportunity_public(row: dict, internal: bool = True) -> dict:
    result = dict(row)
    evidence = loads(result.pop("evidence_json"), {})
    result["score_detail"] = loads(result.pop("score_json"), {})
    if internal:
        result["evidence"] = evidence
    else:
        result.pop("score_detail", None)
        result["evidence"] = {"answer_ids": evidence.get("answer_ids", []),
                              "evidence_count": len(evidence.get("evidence", []))}
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
        return {"items": [opportunity_public(row, context["role"] in ("admin", "analyst")) for row in rows]}


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
    project_context(request, project_id)
    with connect() as conn:
        return {"items": all_rows(conn, """SELECT a.*,o.gap_type,o.eligibility,o.wave_id AS opportunity_wave_id,
            (SELECT COUNT(*) FROM action_assets s WHERE s.action_id=a.id) AS asset_count,
            (SELECT COUNT(*) FROM asset_publications p WHERE p.action_id=a.id) AS publication_count,
            (SELECT r.due_at FROM action_remeasurement_rounds r WHERE r.action_id=a.id ORDER BY r.round_no DESC LIMIT 1) AS latest_round_due_at,
            (SELECT r.status FROM action_remeasurement_rounds r WHERE r.action_id=a.id ORDER BY r.round_no DESC LIMIT 1) AS latest_round_status
            FROM actions a JOIN opportunities o ON o.id=a.opportunity_id WHERE a.project_id=? ORDER BY a.updated_at DESC""", (project_id,))}


@router.get("/actions/{action_id}")
def get_action(project_id: int, action_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        action = scoped_object(conn, "actions", action_id, context["project"])
        return interventions.intervention_detail(conn, action, context["role"])


@router.post("/actions/{action_id}/briefs")
def create_brief(project_id: int, action_id: int, payload: BriefIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        action = scoped_object(conn, "actions", action_id, context["project"])
        row = interventions.create_brief(conn, action, context["user"]["id"], payload.model_dump())
        conn.commit()
        return row


@router.put("/briefs/{brief_id}")
def update_brief(project_id: int, brief_id: int, payload: BriefIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        brief = scoped_object(conn, "content_briefs", brief_id, context["project"])
        row = interventions.update_brief(conn, brief, context["user"]["id"], payload.model_dump())
        conn.commit()
        return row


@router.post("/briefs/{brief_id}/approve")
def approve_brief(project_id: int, brief_id: int, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        brief = scoped_object(conn, "content_briefs", brief_id, context["project"])
        row = interventions.approve_brief(conn, brief, context["user"]["id"])
        conn.commit()
        return row


@router.post("/actions/{action_id}/assets")
def create_asset(project_id: int, action_id: int, payload: AssetIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        action = scoped_object(conn, "actions", action_id, context["project"])
        row = interventions.create_asset(conn, action, context["user"]["id"], payload.model_dump())
        conn.commit()
        return row


@router.put("/assets/{asset_id}")
def update_asset(project_id: int, asset_id: int, payload: AssetIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        asset = scoped_object(conn, "action_assets", asset_id, context["project"])
        row = interventions.update_asset(conn, asset, context["user"]["id"], payload.model_dump())
        conn.commit()
        return row


@router.post("/assets/{asset_id}/approve")
def approve_asset(project_id: int, asset_id: int, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        asset = scoped_object(conn, "action_assets", asset_id, context["project"])
        row = interventions.approve_asset(conn, asset, context["user"]["id"])
        conn.commit()
        return row


@router.post("/actions/{action_id}/publications")
def create_publication(project_id: int, action_id: int, payload: PublicationIn, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        action = scoped_object(conn, "actions", action_id, context["project"])
        row = interventions.record_publication(conn, action, context["user"]["id"], payload.model_dump())
        conn.commit()
        return row


@router.post("/actions/{action_id}/remeasurements")
def create_remeasurements(project_id: int, action_id: int, payload: RemeasurementsIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        action = scoped_object(conn, "actions", action_id, context["project"])
        rows = remeasurements.create_rounds(conn, action, context["user"]["id"],
                                            [item.model_dump() for item in payload.rounds])
        conn.commit()
        return {"items": [interventions.round_public(row) for row in rows]}


@router.post("/remeasurements/{round_id}/assess")
def assess_remeasurement(project_id: int, round_id: int, payload: AssessmentIn, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        round_row = scoped_object(conn, "action_remeasurement_rounds", round_id, context["project"])
        row = remeasurements.assess_round(conn, round_row, context["user"]["id"], payload.reason)
        conn.commit()
        return interventions.round_public(row)


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
