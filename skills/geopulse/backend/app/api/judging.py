"""Judge-only re-evaluation routes; raw answers and original Run state stay immutable."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..db import connect
from ..security import project_context, require_admin
from ..services.judge_batches import (batch_public, cancel_judge_batch, create_judge_batch,
                                      list_judge_batches, retry_judge_batch)
from ..services.state import scoped_object
from .schemas import JudgeBatchIn, JudgeBatchRetryIn

router = APIRouter(prefix="/api/projects/{project_id}", tags=["judging"])


@router.post("/runs/{run_id}/judge-batches")
def new_judge_batch(project_id: int, run_id: int, payload: JudgeBatchIn, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        run = scoped_object(conn, "runs", run_id, context["project"])
    return create_judge_batch(context["project"], context["user"]["id"], run, payload.model_dump(exclude_unset=True))


@router.get("/runs/{run_id}/judge-batches")
def run_judge_batches(project_id: int, run_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        scoped_object(conn, "runs", run_id, context["project"])
        return {"items": list_judge_batches(conn, run_id, context["role"])}


@router.get("/judge-batches/{batch_id}")
def get_judge_batch(project_id: int, batch_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        batch = scoped_object(conn, "judge_batches", batch_id, context["project"])
        return batch_public(conn, batch, include_items=True, role=context["role"])


@router.post("/judge-batches/{batch_id}/cancel")
def cancel(project_id: int, batch_id: int, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        batch = scoped_object(conn, "judge_batches", batch_id, context["project"])
    return cancel_judge_batch(context["project"], context["user"]["id"], batch)


@router.post("/judge-batches/{batch_id}/retry")
def retry(project_id: int, batch_id: int, payload: JudgeBatchRetryIn, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        batch = scoped_object(conn, "judge_batches", batch_id, context["project"])
    return retry_judge_batch(context["project"], context["user"]["id"], batch, payload.model_dump())
