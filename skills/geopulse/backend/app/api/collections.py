"""Project-scoped manual Consumer Web collection and evidence routes."""
from __future__ import annotations

import re
import urllib.parse

from fastapi import APIRouter, Query, Request, Response

from ..db import transaction
from ..security import project_context
from ..services import web_collection
from .schemas import CollectionDraftIn, CollectionFailureIn

router = APIRouter(prefix="/api/projects/{project_id}", tags=["manual-consumer-web"])


@router.get("/answers/{answer_id}/collection")
def get_collection(project_id: int, answer_id: int, request: Request):
    context = project_context(request, project_id)
    with transaction() as conn:
        return web_collection.get_collection(conn, context["project"], answer_id,
                                             internal=context["role"] in ("admin", "analyst"))


@router.put("/answers/{answer_id}/collection/draft")
def save_draft(project_id: int, answer_id: int, payload: CollectionDraftIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with transaction() as conn:
        return web_collection.save_draft(conn, context["project"], answer_id, payload.model_dump(), context["user"]["id"])


@router.post("/answers/{answer_id}/collection/submit")
def submit_collection(project_id: int, answer_id: int, payload: CollectionDraftIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with transaction() as conn:
        return web_collection.submit_collection(conn, context["project"], answer_id, payload.model_dump(), context["user"]["id"])


@router.post("/answers/{answer_id}/collection/fail")
def fail_collection(project_id: int, answer_id: int, payload: CollectionFailureIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with transaction() as conn:
        return web_collection.fail_collection(conn, context["project"], answer_id, payload.model_dump(), context["user"]["id"])


@router.post("/answers/{answer_id}/attachments")
async def upload_attachment(project_id: int, answer_id: int, request: Request,
                            kind: str = Query(), filename: str = Query(), media_type: str = Query()):
    context = project_context(request, project_id, "analyst")
    content = await request.body()
    with transaction() as conn:
        return web_collection.upload_attachment(
            conn, context["project"], answer_id, kind, filename, media_type, content,
            request.headers.get("X-Content-SHA256", ""), context["user"]["id"])


@router.delete("/attachments/{attachment_id}")
def delete_attachment(project_id: int, attachment_id: int, request: Request):
    context = project_context(request, project_id, "analyst")
    with transaction() as conn:
        return web_collection.delete_attachment(conn, context["project"], attachment_id, context["user"]["id"])


@router.get("/attachments/{attachment_id}")
def download_attachment(project_id: int, attachment_id: int, request: Request):
    context = project_context(request, project_id, "analyst")
    with transaction() as conn:
        row = web_collection.get_attachment(conn, context["project"], attachment_id)
    fallback = re.sub(r"[^A-Za-z0-9._-]", "_", row["filename"]) or "evidence.bin"
    disposition = (f"attachment; filename=\"{fallback}\"; filename*=UTF-8''"
                   f"{urllib.parse.quote(row['filename'], safe='')}")
    return Response(row["content"], media_type=row["media_type"], headers={
        "Content-Disposition": disposition,
        "Content-Length": str(row["byte_size"]),
        "X-Content-SHA256": row["sha256"],
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    })
