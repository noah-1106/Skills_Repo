"""Project-scoped brand entity workbench routes."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..db import all_rows, connect, loads
from ..engine.analyzer import alias_conflicts
from ..security import project_context, require_admin
from ..services import entities
from ..services.measurement import entity_public
from ..services.state import scoped_object
from .schemas import EntityIn, EntityReviewIn

router = APIRouter(prefix="/api/projects/{project_id}/entities", tags=["entities"])


@router.get("")
def list_entities(project_id: int, request: Request, include_history: bool = False):
    context = project_context(request, project_id)
    with connect() as conn:
        condition = "" if include_history else "AND valid_to IS NULL"
        rows = all_rows(conn, f"SELECT * FROM brand_entities WHERE project_id=? {condition} ORDER BY role,name,version DESC", (project_id,))
        public = [entity_public(row) for row in rows]
        return {"items": public, "conflicts": alias_conflicts(public)}


@router.post("")
def create_entity(project_id: int, payload: EntityIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        row = entities.create_entity(conn, context["project"], context["user"]["id"], payload.model_dump(), payload.allow_conflicts)
        conn.commit()
        return entity_public(row)


@router.post("/{entity_id}/review")
def review_entity(project_id: int, entity_id: int, payload: EntityReviewIn, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        entity = scoped_object(conn, "brand_entities", entity_id, context["project"])
        row = entities.review_entity(conn, entity, context["user"]["id"], payload.decision, payload.reason, payload.role)
        conn.commit()
        return entity_public(row)


@router.post("/{entity_id}/versions")
def new_version(project_id: int, entity_id: int, payload: EntityIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        entity = scoped_object(conn, "brand_entities", entity_id, context["project"])
        row = entities.new_version(conn, entity, context["user"]["id"], payload.model_dump())
        conn.commit()
        return entity_public(row)


@router.get("/pool-diff")
def pool_diff(project_id: int, request: Request, before: str = "", after: str = ""):
    context = project_context(request, project_id)
    parse = lambda value: [int(item) for item in value.split(",") if item.strip()]
    with connect() as conn:
        return entities.pool_diff(conn, parse(before), parse(after), project_id)
