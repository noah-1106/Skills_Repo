"""Immutable report preview, approval and export routes."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from ..db import all_rows, connect, loads, one
from ..security import audit, project_context, require_admin
from ..services import reporting
from ..services.state import scoped_object
from .schemas import ReportIn, StatusIn

router = APIRouter(prefix="/api/projects/{project_id}/reports", tags=["reports"])


def report_public(row: dict, internal: bool = False) -> dict:
    result = {key: value for key, value in row.items() if key not in ("client_html", "internal_html", "data_snapshot_json")}
    result["wave_ids"] = loads(row["wave_ids_json"], [])
    return result


@router.get("")
def list_reports(project_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        return {"items": [report_public(row) for row in all_rows(conn, "SELECT * FROM reports WHERE project_id=? ORDER BY version DESC", (project_id,))]}


@router.post("")
def create_report(project_id: int, payload: ReportIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        row = reporting.create_report(conn, context["project"], payload.wave_ids, context["user"]["id"])
        conn.commit()
        return report_public(row)


@router.get("/{report_id}")
def get_report(project_id: int, report_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        report = scoped_object(conn, "reports", report_id, context["project"])
        result = report_public(report)
        result["events"] = all_rows(conn, "SELECT * FROM report_events WHERE report_id=? ORDER BY id", (report_id,))
        snapshot = loads(report["data_snapshot_json"], {})
        snapshot["approval_status"] = report["approval_status"]
        if context["role"] in ("reviewer", "viewer"):
            snapshot = reporting.customer_snapshot(snapshot)
        result["snapshot"] = snapshot
        result["gates"] = reporting.release_gates(loads(report["data_snapshot_json"], {}))
        return result


@router.post("/{report_id}/status")
def change_status(project_id: int, report_id: int, payload: StatusIn, request: Request):
    context = require_admin(request, project_id)
    if payload.status == "sent" and not payload.reason.strip():
        raise HTTPException(400, "标记发送时必须登记接收人或发送记录")
    with connect() as conn:
        report = scoped_object(conn, "reports", report_id, context["project"])
        row = reporting.transition_report(conn, report, payload.status, context["user"]["id"], payload.reason)
        conn.commit()
        return report_public(row)


def _pdf(html: str) -> bytes:
    from playwright.sync_api import sync_playwright
    candidates = [os.environ.get("CHROME_PATH"),
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium",
                  "/usr/bin/google-chrome", "/usr/bin/chromium"]
    executable = next((path for path in candidates if path and Path(path).is_file()), None)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable, headless=True)
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            return page.pdf(format="A4", print_background=True,
                            margin={"top": "14mm", "right": "12mm", "bottom": "14mm", "left": "12mm"})
        finally:
            browser.close()


@router.get("/{report_id}/export")
def export_report(project_id: int, report_id: int, request: Request, variant: str = "client", format: str = "html"):
    context = project_context(request, project_id)
    if variant not in ("client", "internal") or format not in ("html", "pdf"):
        raise HTTPException(400, "variant 仅支持 client/internal，format 仅支持 html/pdf")
    if variant == "internal" and context["role"] not in ("admin", "analyst"):
        raise HTTPException(403, "内部版仅对内部角色开放")
    with connect() as conn:
        report = scoped_object(conn, "reports", report_id, context["project"])
    if variant == "client" and format == "pdf" and report["approval_status"] not in ("client_approved", "sent"):
        raise HTTPException(409, "客户版 PDF 必须完成管理员客户审批后导出")
    html = report["internal_html"] if variant == "internal" else report["client_html"]
    html_checksum = report[f"{variant}_html_sha256"] or hashlib.sha256(html.encode()).hexdigest()
    if format == "pdf":
        content = _pdf(html)
        checksum = hashlib.sha256(content).hexdigest()
        media_type = "application/pdf"
        disposition = f'attachment; filename="geopulse-report-{report_id}-v{report["version"]}.pdf"'
    else:
        content = html
        checksum = html_checksum
        media_type = "text/html"
        disposition = f'inline; filename="geopulse-report-{report_id}.html"'
    with connect() as conn:
        audit(conn, context["user"]["id"], context["project"], "report", report_id, "export", None,
              {"variant": variant, "format": format, "sha256": checksum,
               "data_snapshot_hash": report["data_snapshot_hash"]})
        conn.commit()
    headers = {"Content-Disposition": disposition, "X-Content-SHA256": checksum,
               "X-Data-Snapshot-SHA256": report["data_snapshot_hash"]}
    if format == "html":
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
        return HTMLResponse(content, headers=headers)
    return Response(content, media_type=media_type, headers=headers)
