"""Read-only business handoff projection; never writes external business twins."""
from __future__ import annotations

from ..db import all_rows, loads, one
from .quality import run_quality
from .reporting import release_gates


def delivery_handoff(conn, project: dict, run: dict) -> dict:
    wave = one(conn, "SELECT * FROM waves WHERE id=? AND project_id=?", (run["wave_id"], project["id"]))
    quality = run_quality(conn, run)
    opportunities = all_rows(conn, """SELECT id,status,eligibility,score FROM opportunities
        WHERE project_id=? AND wave_id=? ORDER BY id""", (project["id"], wave["id"]))
    opportunity_audit = one(conn, """SELECT id,created_at,after_json FROM audit_events
        WHERE project_id=? AND object_type='wave' AND object_id=? AND action='generate_opportunities'
        ORDER BY id DESC LIMIT 1""", (project["id"], str(wave["id"])))
    reports = [row for row in all_rows(conn, "SELECT * FROM reports WHERE project_id=? ORDER BY version DESC", (project["id"],))
               if wave["id"] in loads(row["wave_ids_json"], [])]
    report = reports[0] if reports else None
    report_gates = release_gates(loads(report["data_snapshot_json"], {})) if report else []
    work = one(conn, "SELECT COUNT(*) AS entries,COALESCE(SUM(hours),0) AS hours FROM work_logs WHERE project_id=?",
               (project["id"],))
    if quality["next_action"]["kind"] != "ready":
        next_action = quality["next_action"]
    elif not opportunity_audit:
        next_action = {"kind": "generate_opportunities", "wave_id": wave["id"]}
    elif any(item["status"] in ("candidate", "eligibility_pending") for item in opportunities):
        next_action = {"kind": "review_opportunities", "wave_id": wave["id"]}
    elif not report:
        next_action = {"kind": "create_report", "wave_id": wave["id"]}
    elif report_gates and report["approval_status"] not in ("client_approved", "sent"):
        next_action = {"kind": "create_report", "wave_id": wave["id"],
                       "reason": "最新报告快照仍有质量阻断；创建新版本冻结当前事实"}
    elif report["approval_status"] not in ("client_approved", "sent"):
        next_action = {"kind": "approve_report", "report_id": report["id"]}
    elif not work["entries"]:
        next_action = {"kind": "record_work_log_reminder", "project_id": project["id"],
                       "note": "仅提醒人工登记；不会把 Run 时长自动记为咨询工时"}
    elif wave["status"] not in ("analyzed", "closed"):
        next_action = {"kind": "close_or_analyze_wave", "wave_id": wave["id"]}
    else:
        next_action = {"kind": "complete", "wave_id": wave["id"]}
    opportunity_result = loads(opportunity_audit["after_json"], {}) if opportunity_audit else {}
    return {
        "project": {"id": project["id"], "name": project["name"], "client_id": project["client_id"]},
        "wave": {"id": wave["id"], "label": wave["label"], "status": wave["status"],
                 "official_run_id": wave["official_run_id"]},
        "run": {"id": run["id"], "attempt_no": run["attempt_no"], "status": run["status"]},
        "quality": quality, "delivery_readiness": quality["delivery_readiness"], "next_action": next_action,
        "opportunities": {
            "checked": bool(opportunity_audit), "checked_at": opportunity_audit["created_at"] if opportunity_audit else None,
            "generated_count": int(opportunity_result.get("count") or 0),
            "empty_result": bool(opportunity_audit) and not opportunities,
            "status": "not_checked" if not opportunity_audit else "checked_empty" if not opportunities else "checked",
            "items": opportunities,
        },
        "report": ({"id": report["id"], "version": report["version"],
                    "approval_status": report["approval_status"], "updated_at": report["updated_at"],
                    "gates": report_gates} if report else None),
        "work_log": {"entries": work["entries"], "hours": work["hours"], "missing": not work["entries"],
                     "mode": "manual_reminder_only"},
        "external_sync": {"automatic": False, "note": "GeoPulse 不写外部业务孪生、不自动外发报告；同步方应自行记录 synced_at。"},
    }
