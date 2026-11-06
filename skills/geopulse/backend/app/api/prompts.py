"""Project-scoped prompt-set workbench routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from ..db import all_rows, connect, loads, one
from ..security import project_context, require_admin
from ..services import prompts
from ..services.measurement import prompt_set_content
from ..services.state import scoped_object, transition
from .schemas import ItemReviewIn, ItemsIn, PromptSetIn, ScaffoldIn, StatusIn

router = APIRouter(prefix="/api/projects/{project_id}/prompt-sets", tags=["prompt-sets"])


def serialize(conn, row: dict, include_items: bool = True) -> dict:
    result = dict(row)
    result["weights"] = loads(result.pop("weights_json"), {})
    if include_items:
        result["items"] = prompt_set_content(conn, row["id"])
    return result


def get_set(conn, project: dict, set_id: int) -> dict:
    return scoped_object(conn, "prompt_sets", set_id, project)


@router.get("")
def list_sets(project_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        rows = all_rows(conn, "SELECT * FROM prompt_sets WHERE project_id=? ORDER BY version DESC", (project_id,))
        return {"items": [serialize(conn, row, include_items=False) for row in rows]}


@router.post("")
def create_set(project_id: int, payload: PromptSetIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        row = prompts.create_set(conn, context["project"], context["user"]["id"], payload.name, payload.weights)
        conn.commit()
        return serialize(conn, row)


@router.get("/{set_id}")
def get_prompt_set(project_id: int, set_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        return serialize(conn, get_set(conn, context["project"], set_id))


@router.post("/{set_id}/items")
def add_items(project_id: int, set_id: int, payload: ItemsIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        prompt_set = get_set(conn, context["project"], set_id)
        result = prompts.add_items(conn, prompt_set, context["user"]["id"], payload.items, payload.redact)
        conn.commit()
        return {**result, "count": len(result["items"])}


@router.post("/scaffold/preview")
def scaffold_preview(project_id: int, payload: ScaffoldIn, request: Request):
    project_context(request, project_id, "analyst")
    return {"items": prompts.scaffold(payload.brand, payload.category, payload.competitors, payload.market),
            "review_required": True, "note": "候选题不会自动进入基线，请去重、审核后再冻结。"}


@router.post("/{set_id}/items/{item_id}/review")
def review_item(project_id: int, set_id: int, item_id: int, payload: ItemReviewIn, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        prompt_set = get_set(conn, context["project"], set_id)
        row = prompts.review_item(conn, prompt_set, item_id, context["user"]["id"], payload.status, payload.eligibility)
        conn.commit()
        return row


@router.post("/{set_id}/status")
def change_status(project_id: int, set_id: int, payload: StatusIn, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        prompt_set = get_set(conn, context["project"], set_id)
        if payload.status == "frozen":
            row = prompts.freeze_set(conn, prompt_set, context["user"]["id"], context["project"])
        else:
            if payload.status not in ("reviewing", "draft", "retired"):
                raise HTTPException(400, "无效问题集状态")
            row = transition(conn, "prompt_sets", prompt_set, payload.status, context["user"]["id"], payload.reason)
        conn.commit()
        return row


@router.post("/{set_id}/copy")
def copy_set(project_id: int, set_id: int, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        prompt_set = get_set(conn, context["project"], set_id)
        if prompt_set["status"] != "frozen":
            raise HTTPException(409, "只有冻结版本需要复制；草稿可直接编辑")
        row = prompts.copy_set(conn, prompt_set, context["user"]["id"])
        conn.commit()
        return serialize(conn, row)


@router.get("/{set_id}/diff/{other_id}")
def diff(project_id: int, set_id: int, other_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        before = prompt_set_content(conn, get_set(conn, context["project"], set_id)["id"])
        after = prompt_set_content(conn, get_set(conn, context["project"], other_id)["id"])
        return prompts.diff_sets(before, after)


@router.get("/{set_id}/export")
def export(project_id: int, set_id: int, request: Request, format: str = "json"):
    context = project_context(request, project_id)
    with connect() as conn:
        prompt_set = get_set(conn, context["project"], set_id)
        items = prompt_set_content(conn, set_id)
    if format == "csv":
        return PlainTextResponse(prompts.export_csv(items), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="prompt-set-{set_id}.csv"'})
    if format != "json":
        raise HTTPException(400, "仅支持 json 或 csv")
    return {"schema_version": 1, "project_id": project_id, "prompt_set": serialize_dict(prompt_set), "items": items}


def serialize_dict(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "version": row["version"], "status": row["status"],
            "content_hash": row["content_hash"], "weights": loads(row["weights_json"], {})}
