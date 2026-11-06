"""Administration, engine secrets, scheduling, costs and data governance."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from .. import config
from ..db import all_rows, connect, dumps, loads, one, utc_now
from ..migrations import backup
from ..providers import build_provider
from ..security import (SecretStore, audit, current_user, hash_password, project_context, require_admin)
from ..services.measurement import engine_public
from ..services.state import scoped_object
from .schemas import EngineIn, HealthCheckIn, MembershipIn, ScheduleIn, UserIn, WorkLogIn

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/projects/{project_id}/engines")
def list_engines(project_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        return {"items": [engine_public(row) for row in all_rows(conn, "SELECT * FROM engine_configs WHERE project_id=? ORDER BY id", (project_id,))]}


def validate_engine(payload: EngineIn) -> None:
    if payload.measurement_target != "provider_api":
        raise HTTPException(400, "当前仅支持合法 provider_api 采集，不能把 API 结果标为产品端")
    if payload.kind == "demo" and payload.mode != "memory":
        raise HTTPException(400, "demo 仅用于 memory 演示")
    if payload.kind == "openai_compat" and payload.mode != "memory":
        raise HTTPException(400, "普通 OpenAI-compatible 引擎只能使用 memory；Kimi 检索请选择 kimi_search")
    if payload.kind == "kimi_search" and payload.mode != "search":
        raise HTTPException(400, "kimi_search 必须使用 search 模式")
    if payload.kind != "demo" and (not payload.base_url.startswith("https://") or not payload.model):
        raise HTTPException(400, "生产引擎必须配置 HTTPS Base URL 和模型")


@router.post("/projects/{project_id}/engines")
def create_engine(project_id: int, payload: EngineIn, request: Request):
    context = require_admin(request, project_id)
    validate_engine(payload)
    if payload.kind != "demo" and not payload.api_key:
        raise HTTPException(400, "生产引擎需要 API Key")
    with connect() as conn:
        ref = SecretStore().put(payload.api_key) if payload.api_key else ""
        engine_id = conn.execute("INSERT INTO engine_configs(client_id,project_id,name,vendor,kind,model,base_url,secret_ref,mode,measurement_target,region,cost_rule_json,timeout,rate_limit,enabled,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (context["project"]["client_id"], project_id, payload.name, payload.vendor, payload.kind,
                                  payload.model, payload.base_url.rstrip("/"), ref, payload.mode, payload.measurement_target,
                                  payload.region, dumps(payload.cost_rule), payload.timeout, payload.rate_limit,
                                  int(payload.enabled), utc_now())).lastrowid
        row = one(conn, "SELECT * FROM engine_configs WHERE id=?", (engine_id,))
        audit(conn, context["user"]["id"], context["project"], "engine", engine_id, "create", None, engine_public(row))
        conn.commit()
        return engine_public(row)


@router.put("/projects/{project_id}/engines/{engine_id}")
def update_engine(project_id: int, engine_id: int, payload: EngineIn, request: Request):
    context = require_admin(request, project_id)
    validate_engine(payload)
    with connect() as conn:
        old = scoped_object(conn, "engine_configs", engine_id, context["project"])
        ref = old["secret_ref"]
        if payload.api_key and payload.api_key != "__KEEP__":
            ref = SecretStore().put(payload.api_key, ref or None)
        if old["kind"] != "demo" and not SecretStore().get(ref):
            raise HTTPException(400, "请填写 API Key")
        conn.execute("UPDATE engine_configs SET name=?,vendor=?,kind=?,model=?,base_url=?,secret_ref=?,mode=?,measurement_target=?,region=?,cost_rule_json=?,timeout=?,rate_limit=?,enabled=? WHERE id=?",
                     (payload.name, payload.vendor, payload.kind, payload.model, payload.base_url.rstrip("/"), ref,
                      payload.mode, payload.measurement_target, payload.region, dumps(payload.cost_rule), payload.timeout,
                      payload.rate_limit, int(payload.enabled), engine_id))
        row = one(conn, "SELECT * FROM engine_configs WHERE id=?", (engine_id,))
        audit(conn, context["user"]["id"], context["project"], "engine", engine_id, "update", engine_public(old), engine_public(row))
        conn.commit()
        return engine_public(row)


@router.post("/projects/{project_id}/engines/{engine_id}/health")
def engine_health(project_id: int, engine_id: int, request: Request, payload: HealthCheckIn | None = None):
    context = require_admin(request, project_id)
    with connect() as conn:
        engine = scoped_object(conn, "engine_configs", engine_id, context["project"])
    if engine["kind"] != "demo" and (not payload or not payload.confirm):
        raise HTTPException(409, "真实健康检查会产生外部调用；请确认预估调用次数和费用后重试")
    provider = build_provider(engine, SecretStore().get(engine["secret_ref"]), ["GeoPulse", "Profound"])
    try:
        result = provider.ask("只回答：健康检查通过", {"max_tokens": 8, "temperature": 0})
        status, detail = "healthy", f"{result.model} / {result.latency_ms}ms"
    except Exception as error:
        status, detail = "unhealthy", str(error)[:300]
    with connect() as conn:
        conn.execute("UPDATE engine_configs SET health_status=? WHERE id=?", (f"{status}:{detail}", engine_id))
        audit(conn, context["user"]["id"], context["project"], "engine", engine_id, "paid_health_check", None,
              {"status": status, "detail": detail})
        conn.commit()
    return {"status": status, "detail": detail}


@router.get("/users")
def list_users(request: Request):
    user = current_user(request)
    if user["global_role"] != "admin":
        raise HTTPException(403, "仅全局管理员可管理用户")
    with connect() as conn:
        return {"items": all_rows(conn, "SELECT id,email,global_role,status,created_at FROM users ORDER BY id")}


@router.post("/users")
def create_user(payload: UserIn, request: Request):
    actor = current_user(request)
    if actor["global_role"] != "admin":
        raise HTTPException(403, "仅全局管理员可创建用户")
    with connect() as conn:
        user_id = conn.execute("INSERT INTO users(email,password_hash,created_at) VALUES(?,?,?)",
                               (payload.email.strip(), hash_password(payload.password), utc_now())).lastrowid
        audit(conn, actor["id"], None, "user", user_id, "create", None, {"email": payload.email})
        conn.commit()
        return {"id": user_id, "email": payload.email}


@router.post("/projects/{project_id}/memberships")
def assign_member(project_id: int, payload: MembershipIn, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        conn.execute("INSERT INTO memberships(client_id,project_id,user_id,role,created_at) VALUES(?,?,?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role",
                     (context["project"]["client_id"], project_id, payload.user_id, payload.role, utc_now()))
        audit(conn, context["user"]["id"], context["project"], "membership", payload.user_id, "assign", None,
              {"role": payload.role})
        conn.commit()
    return {"ok": True}


@router.get("/projects/{project_id}/memberships")
def list_members(project_id: int, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        return {"items": all_rows(conn, "SELECT m.*,u.email FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.project_id=?", (project_id,))}


@router.get("/projects/{project_id}/schedules")
def schedules(project_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        return {"items": all_rows(conn, "SELECT s.*,w.label AS wave_label FROM schedules s JOIN waves w ON w.id=s.wave_id WHERE s.project_id=? ORDER BY s.scheduled_at", (project_id,))}


@router.post("/projects/{project_id}/schedules")
def create_schedule(project_id: int, payload: ScheduleIn, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        scoped_object(conn, "waves", payload.wave_id, context["project"])
        schedule_id = conn.execute("INSERT INTO schedules(client_id,project_id,wave_id,scheduled_at,created_at) VALUES(?,?,?,?,?)",
                                   (context["project"]["client_id"], project_id, payload.wave_id, payload.scheduled_at, utc_now())).lastrowid
        audit(conn, context["user"]["id"], context["project"], "schedule", schedule_id, "create", None, payload.model_dump())
        conn.commit()
        return one(conn, "SELECT * FROM schedules WHERE id=?", (schedule_id,))


@router.get("/projects/{project_id}/alerts")
def alerts(project_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        return {"items": all_rows(conn, "SELECT * FROM alerts WHERE project_id=? ORDER BY id DESC LIMIT 200", (project_id,))}


@router.post("/projects/{project_id}/alerts/{alert_id}/ack")
def acknowledge_alert(project_id: int, alert_id: int, request: Request):
    context = require_admin(request, project_id)
    with connect() as conn:
        result = conn.execute("UPDATE alerts SET status='acknowledged' WHERE id=? AND project_id=?", (alert_id, project_id))
        if not result.rowcount:
            raise HTTPException(404, "告警不存在")
        conn.commit()
    return {"ok": True}


@router.get("/projects/{project_id}/audit")
def audit_log(project_id: int, request: Request, limit: int = 100):
    context = require_admin(request, project_id)
    with connect() as conn:
        rows = all_rows(conn, "SELECT a.*,u.email AS actor_email FROM audit_events a LEFT JOIN users u ON u.id=a.actor WHERE a.project_id=? ORDER BY a.id DESC LIMIT ?", (project_id, min(500, max(1, limit))))
        for row in rows:
            row["before"] = loads(row.pop("before_json"), None)
            row["after"] = loads(row.pop("after_json"), None)
        return {"items": rows}


@router.post("/projects/{project_id}/work-logs")
def create_work_log(project_id: int, payload: WorkLogIn, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        log_id = conn.execute("INSERT INTO work_logs(client_id,project_id,user_id,hours,kind,note,created_at) VALUES(?,?,?,?,?,?,?)",
                              (context["project"]["client_id"], project_id, context["user"]["id"], payload.hours,
                               payload.kind, payload.note, utc_now())).lastrowid
        conn.commit()
        return one(conn, "SELECT * FROM work_logs WHERE id=?", (log_id,))


@router.get("/projects/{project_id}/operations")
def operations(project_id: int, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        costs = all_rows(conn, "SELECT c.kind,COUNT(*) AS calls,SUM(c.cost) AS cost,SUM(CASE WHEN c.cost IS NULL THEN 1 ELSE 0 END) AS unknown FROM call_attempts c JOIN answers a ON a.id=c.answer_id WHERE a.project_id=? GROUP BY c.kind", (project_id,))
        queue = {row["status"]: row["count"] for row in conn.execute("SELECT status,COUNT(*) AS count FROM answers WHERE project_id=? GROUP BY status", (project_id,))}
        hours = one(conn, "SELECT COALESCE(SUM(hours),0) AS value FROM work_logs WHERE project_id=?", (project_id,))["value"]
        logs = all_rows(conn, "SELECT w.*,u.email FROM work_logs w LEFT JOIN users u ON u.id=w.user_id WHERE w.project_id=? ORDER BY w.id DESC LIMIT 100", (project_id,))
        return {"costs": costs, "queue": queue, "work_hours": hours, "work_logs": logs,
                "db_bytes": config.db_path().stat().st_size if config.db_path().exists() else 0}


@router.post("/projects/{project_id}/backup")
def create_backup(project_id: int, request: Request):
    context = require_admin(request, project_id)
    manifest = backup()
    with connect() as conn:
        audit(conn, context["user"]["id"], context["project"], "database", project_id, "backup", None, manifest)
        conn.commit()
    return manifest


@router.get("/projects/{project_id}/export")
def export_project(project_id: int, request: Request):
    context = require_admin(request, project_id)
    tables = ("clients", "projects", "memberships", "engine_configs", "brand_entities", "prompt_sets", "prompt_items",
              "waves", "runs", "answers", "call_attempts", "observations", "citations", "opportunities", "actions",
              "external_events", "reports", "report_events", "schedules", "alerts", "work_logs", "audit_events")
    payload = {"schema_version": 1, "project_id": project_id, "exported_at": utc_now(), "tables": {}}
    with connect() as conn:
        for table in tables:
            if table == "clients":
                rows = all_rows(conn, "SELECT * FROM clients WHERE id=?", (context["project"]["client_id"],))
            elif table == "projects":
                rows = [context["project"]]
            elif table == "report_events":
                rows = all_rows(conn, "SELECT * FROM report_events WHERE report_id IN (SELECT id FROM reports WHERE project_id=?)", (project_id,))
            elif table == "call_attempts":
                rows = all_rows(conn, "SELECT * FROM call_attempts WHERE answer_id IN (SELECT id FROM answers WHERE project_id=?)", (project_id,))
            else:
                rows = all_rows(conn, f"SELECT * FROM {table} WHERE project_id=?", (project_id,))
            if table == "engine_configs":
                for row in rows:
                    row["secret_ref"] = ""
            payload["tables"][table] = rows
    canonical = dumps(payload)
    payload["sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return payload
