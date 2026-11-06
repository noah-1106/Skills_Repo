"""Shared business state machines and scoped persistence helpers."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException

from ..db import one, utc_now
from ..security import audit

TRANSITIONS = {
    "prompt_sets": {
        "draft": {"reviewing"}, "reviewing": {"draft", "frozen"},
        "frozen": {"retired"}, "retired": set(),
    },
    "waves": {
        "planned": {"running", "closed"}, "running": {"data_ready", "data_ready_with_warnings", "closed"},
        "data_ready": {"analyzed", "running", "closed"},
        "data_ready_with_warnings": {"analyzed", "running", "closed"},
        "analyzed": {"closed", "running"}, "closed": set(),
    },
    "opportunities": {
        "candidate": {"eligibility_pending", "rejected"},
        "eligibility_pending": {"confirmed", "rejected", "candidate"},
        "confirmed": {"actioned", "rejected"}, "actioned": {"remeasured", "closed"},
        "remeasured": {"closed", "actioned"}, "rejected": {"candidate"},
        "closed": set(),
    },
    "actions": {
        "draft": {"review", "stopped"}, "review": {"approved", "draft"},
        "approved": {"published", "draft"}, "published": {"remeasure_due"},
        "remeasure_due": {"verified", "not_effective", "stopped"},
        "verified": set(), "not_effective": {"draft"}, "stopped": {"draft"},
    },
    "reports": {
        "draft": {"data_checked"}, "data_checked": {"strategy_reviewed", "draft"},
        "strategy_reviewed": {"client_approved", "draft"},
        "client_approved": {"sent", "draft"}, "sent": set(),
    },
}


def logical_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def scoped_object(conn, table: str, object_id: int, project: dict) -> dict:
    allowed = {"waves", "runs", "answers", "prompt_sets", "brand_entities", "opportunities",
               "actions", "reports", "engine_configs", "observations", "schedules", "alerts"}
    if table not in allowed:
        raise ValueError("unsupported scoped table")
    row = one(conn, f"SELECT * FROM {table} WHERE id=? AND project_id=? AND client_id=?",
              (object_id, project["id"], project["client_id"]))
    if not row:
        raise HTTPException(404, "对象不存在或不属于当前项目")
    return row


def transition(conn, table: str, row: dict, new_status: str, actor: int,
               reason: str = "", extra: dict[str, Any] | None = None) -> dict:
    old_status = row["status"] if "status" in row else row["approval_status"]
    if new_status not in TRANSITIONS.get(table, {}).get(old_status, set()):
        raise HTTPException(409, f"不允许从 {old_status} 变更为 {new_status}")
    if new_status == "draft" and old_status != "reviewing" and not reason:
        raise HTTPException(400, "回退必须填写理由")
    status_field = "approval_status" if table == "reports" else "status"
    updates = {status_field: new_status, **(extra or {})}
    if table in ("opportunities", "actions", "reports"):
        updates["updated_at"] = utc_now()
    assignments = ",".join(f"{key}=?" for key in updates)
    conn.execute(f"UPDATE {table} SET {assignments} WHERE id=?", (*updates.values(), row["id"]))
    after = {**row, **updates}
    audit(conn, actor, row, table, row["id"], f"status:{old_status}->{new_status}",
          {"status": old_status, "reason": reason}, {"status": new_status, "reason": reason})
    if table == "reports":
        conn.execute("INSERT INTO report_events(report_id,actor,from_status,to_status,reason,created_at) VALUES(?,?,?,?,?,?)",
                     (row["id"], actor, old_status, new_status, reason, utc_now()))
    return after
