"""One complete, tenant-scoped export contract for the API and CLI."""
from __future__ import annotations

import hashlib
import base64
import json

from ..db import all_rows, dumps, utc_now
from ..migrations import SCHEMA_VERSION
from ..security import audit

TABLES = ("clients", "projects", "memberships", "engine_configs", "brand_entities", "prompt_sets", "prompt_items",
          "waves", "runs", "answers", "call_attempts", "observations", "citations", "opportunities", "actions",
          "external_events", "reports", "report_events", "schedules", "alerts", "work_logs", "audit_events",
          "budget_reservations", "retention_runs", "backup_runs", "web_collections", "answer_attachments")


def sanitize(value):
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in ("api_key", "password_hash", "authorization"):
                continue
            if key == "secret_ref":
                result[key] = ""
            elif key.endswith("_json") and isinstance(item, str):
                try:
                    parsed = json.loads(item)
                except json.JSONDecodeError:
                    result[key] = item
                else:
                    result[key] = dumps(sanitize(parsed)) if isinstance(parsed, (dict, list)) else item
            else:
                result[key] = sanitize(item)
        return result
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def build_project_export(conn, project: dict, actor: int | None = None) -> dict:
    audit(conn, actor, project, "project", project["id"], "export", None,
          {"schema_version": SCHEMA_VERSION, "contract": "geopulse-project-v2"})
    payload = {"schema_version": SCHEMA_VERSION, "export_contract": "geopulse-project-v2",
               "project_id": project["id"], "project": sanitize(project), "exported_at": utc_now(), "tables": {}}
    for table in TABLES:
        if table == "clients":
            rows = all_rows(conn, "SELECT * FROM clients WHERE id=?", (project["client_id"],))
        elif table == "projects":
            rows = [project]
        elif table == "report_events":
            rows = all_rows(conn, "SELECT * FROM report_events WHERE report_id IN (SELECT id FROM reports WHERE project_id=?)", (project["id"],))
        else:
            rows = all_rows(conn, f"SELECT * FROM {table} WHERE project_id=?", (project["id"],))
        payload["tables"][table] = sanitize(rows)
    payload["sha256"] = hashlib.sha256(dumps(payload).encode()).hexdigest()
    return payload
