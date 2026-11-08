"""Explicit per-project raw-content retention with metric-safe tombstones."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from ..db import all_rows, dumps, loads, one, transaction, utc_now
from ..security import audit


def _days(project: dict) -> int | None:
    value = loads(project.get("settings_json"), {}).get("retention_days")
    if value in (None, "", 0, "0"):
        return None
    days = int(value)
    if days < 1:
        raise HTTPException(400, "保留天数必须为正整数；空值或 0 表示不自动清理")
    return days


def preview_retention(conn, project: dict) -> dict:
    days = _days(project)
    if days is None:
        return {"enabled": False, "candidate_count": 0, "cutoff": None,
                "message": "未配置保留期限，原始回答不会自动删除"}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    count = one(conn, """SELECT COUNT(*) AS count FROM answers WHERE project_id=? AND content_retained=1
        AND (raw_text IS NOT NULL AND trim(raw_text)!='' OR EXISTS(SELECT 1 FROM web_collections w WHERE w.answer_id=answers.id AND trim(w.draft_text)!='')
             OR EXISTS(SELECT 1 FROM answer_attachments a WHERE a.answer_id=answers.id AND a.content IS NOT NULL))
        AND status IN ('succeeded','failed','cancelled')
        AND COALESCE(completed_at,created_at)<?""", (project["id"], cutoff))["count"]
    return {"enabled": True, "retention_days": days, "candidate_count": count, "cutoff": cutoff,
            "message": "仅清理到期原文；判定、有效样本事实与聚合指标保留"}


def execute_retention(project: dict, actor: int | None, *, conn=None) -> dict:
    if conn is not None:
        return _execute(conn, project, actor)
    with transaction() as owned:
        return _execute(owned, project, actor)


def _execute(conn, project: dict, actor: int | None) -> dict:
    preview = preview_retention(conn, project)
    started = utc_now()
    if not preview["enabled"]:
        return preview | {"purged_count": 0, "status": "skipped"}
    answers = conn.execute("""SELECT id FROM answers WHERE project_id=? AND content_retained=1
        AND (raw_text IS NOT NULL AND trim(raw_text)!='' OR EXISTS(SELECT 1 FROM web_collections w WHERE w.answer_id=answers.id AND trim(w.draft_text)!='')
             OR EXISTS(SELECT 1 FROM answer_attachments a WHERE a.answer_id=answers.id AND a.content IS NOT NULL))
        AND status IN ('succeeded','failed','cancelled')
        AND COALESCE(completed_at,created_at)<?""", (project["id"], preview["cutoff"])).fetchall()
    ids = [int(row["id"]) for row in answers]
    if ids:
        marks = ",".join("?" for _ in ids)
        conn.execute(f"""UPDATE answers SET valid_sample=CASE
                WHEN status='succeeded' AND raw_text IS NOT NULL AND trim(raw_text)!='' THEN 1
                WHEN status IN ('failed','cancelled') THEN 0 ELSE valid_sample END,
            raw_text=NULL,content_retained=0,content_purged_at=?,error_detail=NULL
            WHERE project_id=? AND id IN ({marks}) AND content_retained=1""",
                     [utc_now(), project["id"], *ids])
    purged = conn.execute("SELECT changes() AS count").fetchone()["count"] if ids else 0
    attachment_purged = 0
    if ids:
        conn.execute(f"UPDATE answer_attachments SET content=NULL,purged_at=? WHERE project_id=? AND answer_id IN ({marks}) AND content IS NOT NULL",
                     [utc_now(), project["id"], *ids])
        attachment_purged = conn.execute("SELECT changes() AS count").fetchone()["count"]
        collections = all_rows(conn, f"SELECT id,citations_json FROM web_collections WHERE project_id=? AND answer_id IN ({marks})",
                               [project["id"], *ids])
        for collection in collections:
            citations = loads(collection["citations_json"], [])
            for citation in citations:
                citation["text"] = ""
            conn.execute("""UPDATE web_collections SET draft_text='',citations_json=?,conversation_url='',
                            browser_phase_detail='',content_purged_at=?,updated_at=? WHERE id=?""",
                         (dumps(citations), utc_now(), utc_now(), collection["id"]))
    finished = utc_now()
    run_id = conn.execute("INSERT INTO retention_runs(client_id,project_id,cutoff,status,candidate_count,purged_count,actor,created_at,finished_at) VALUES(?,?,?,'succeeded',?,?,?,?,?)",
                          (project["client_id"], project["id"], preview["cutoff"], len(ids), purged,
                           actor, started, finished)).lastrowid
    result = {**preview, "purged_count": purged, "attachment_purged_count": attachment_purged,
              "status": "succeeded", "retention_run_id": run_id}
    audit(conn, actor, project, "retention", run_id, "execute", None, result)
    return result


def run_due_retention() -> int:
    with transaction() as conn:
        projects = due_retention_projects(conn)
    completed = 0
    for scheduled in projects:
        try:
            with transaction() as conn:
                project = one(conn, "SELECT * FROM projects WHERE id=?", (scheduled["id"],))
                if project in due_retention_projects(conn):
                    execute_retention(project, None, conn=conn)
                    completed += 1
        except Exception as error:
            with transaction() as conn:
                now = utc_now()
                run_id = conn.execute("INSERT INTO retention_runs(client_id,project_id,cutoff,status,error,created_at,finished_at) VALUES(?,?,?,'failed',?,?,?)",
                                      (scheduled["client_id"], scheduled["id"], now, str(error)[:500], now, now)).lastrowid
                conn.execute("INSERT INTO alerts(client_id,project_id,kind,severity,message,dedupe_key,created_at,updated_at) VALUES(?,?,'retention_failed','critical',?,?,?,?) ON CONFLICT DO NOTHING",
                             (scheduled["client_id"], scheduled["id"], "保留策略执行失败，请检查审计后重试",
                              f"retention-failed:{scheduled['id']}", now, now))
                audit(conn, None, scheduled, "retention", run_id, "execute", None,
                      {"status": "failed", "error": str(error)[:500]})
    return completed


def due_retention_projects(conn) -> list[dict]:
    projects = conn.execute("SELECT * FROM projects WHERE status='active'").fetchall()
    due = []
    for row in projects:
        project = dict(row)
        if _days(project) is None:
            continue
        latest = one(conn, "SELECT created_at FROM retention_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (project["id"],))
        if not latest or latest["created_at"] <= (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds"):
            due.append(project)
    return due
