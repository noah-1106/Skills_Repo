"""Administration, engine secrets, scheduling, costs and data governance."""
from __future__ import annotations

import uuid
import urllib.parse
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request

from .. import config
from ..db import all_rows, connect, dumps, loads, one, transaction, utc_now
from ..migrations import backup
from ..providers import ProviderError, build_provider
from ..security import (SecretStore, audit, current_user, hash_password, project_context, require_admin)
from ..services.budgets import authorize_budget, estimate_health, project_day, release, reserve
from ..services.costs import record_attempt, summarize_costs
from ..services.exports import build_project_export
from ..services.measurement import engine_execution, engine_public
from ..services.state import scoped_object
from ..services.scheduler import iso, parse_time
from ..services.retention import execute_retention, preview_retention
from .schemas import EngineIn, HealthCheckIn, MembershipIn, RetentionIn, ScheduleIn, ScheduleUpdateIn, UserIn, WorkLogIn

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/projects/{project_id}/engines")
def list_engines(project_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        return {"items": [engine_public(row, include_internal=context["role"] == "admin") for row in all_rows(conn, "SELECT * FROM engine_configs WHERE project_id=? ORDER BY id", (project_id,))]}


def validate_engine(payload: EngineIn) -> None:
    if payload.kind == "manual_web":
        parsed = urllib.parse.urlparse(payload.base_url)
        if payload.measurement_target != "consumer_web" or parsed.scheme != "https" or not parsed.hostname:
            raise HTTPException(400, "人工 Consumer Web 目标必须声明 consumer_web 并提供 HTTPS 产品入口")
        if payload.api_key:
            raise HTTPException(400, "人工 Consumer Web 目标不保存 API Key、Cookie 或登录 Token")
        return
    if payload.measurement_target != "provider_api":
        raise HTTPException(400, "Provider 引擎只能使用 provider_api；网页观察请创建 manual_web 目标")
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
    if payload.kind not in ("demo", "manual_web") and not payload.api_key:
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
        if (old["kind"] == "manual_web") != (payload.kind == "manual_web"):
            raise HTTPException(409, "Provider 引擎与人工 Web 目标不能互相改型，请新建独立配置")
        ref = old["secret_ref"]
        if payload.api_key and payload.api_key != "__KEEP__":
            ref = SecretStore().put(payload.api_key)
        if old["kind"] not in ("demo", "manual_web") and not SecretStore().get(ref):
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
    reason = payload.budget_confirmation_reason if payload else ""
    operation_id = f"health-{uuid.uuid4().hex}"
    with transaction() as conn:
        engine = scoped_object(conn, "engine_configs", engine_id, context["project"])
        if engine["kind"] == "manual_web":
            raise HTTPException(409, "人工 Consumer Web 目标没有 Provider 健康检查或外部调用")
        estimate = estimate_health(engine)
        decision = authorize_budget(conn, context["project"], estimate, actor=context["user"]["id"],
                                    confirmation_reason=reason)
        reserve(conn, context["project"], decision, operation_id=operation_id, actor=context["user"]["id"])
    if engine["kind"] != "demo" and (not payload or not payload.confirm):
        with transaction() as conn:
            release(conn=conn, operation_id=operation_id)
        raise HTTPException(409, detail={"code": "health_confirmation_required",
                                        "message": "真实健康检查会产生外部调用，请确认预估后重试", "estimate": estimate})
    operations = []
    try:
        provider = build_provider(engine, SecretStore().get(engine["secret_ref"]), ["GeoPulse", "Profound"])
        result = provider.ask("只回答：健康检查通过", {"max_tokens": 8, "temperature": 0})
        operations = result.operations
        status, detail = "healthy", f"{result.model} / {result.latency_ms}ms"
    except Exception as error:
        operations = error.operations if isinstance(error, ProviderError) else []
        status, detail = "unhealthy", str(error)[:300]
        if not operations:
            operations = [{"kind": "search" if isinstance(error, ProviderError) and error.kind.startswith("search") else "answer",
                           "status": "failed", "error_type": getattr(error, "kind", type(error).__name__),
                           "error_detail": detail}]
    with transaction() as conn:
        for operation in operations:
            record_attempt(conn, project=context["project"], engine=engine_execution(engine),
                           operation=operation, group="health")
        release(conn=conn, operation_id=operation_id)
        conn.execute("UPDATE engine_configs SET health_status=? WHERE id=?", (f"{status}:{detail}", engine_id))
        audit(conn, context["user"]["id"], context["project"], "engine", engine_id, "paid_health_check", None,
              {"status": status, "detail": detail, "operation_id": operation_id,
               "budget_override_reason": decision.get("override_reason") or ""})
    return {"status": status, "detail": detail, "estimate": estimate}


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
    with transaction() as conn:
        wave = scoped_object(conn, "waves", payload.wave_id, context["project"])
        if loads(wave["protocol_json"], {}).get("measurement_target") == "consumer_web":
            raise HTTPException(409, "人工 Consumer Web 不能自动调度；请在测量页显式创建人工采集 Run")
        anchor = wave["anchor_at"]
        if payload.action_id:
            action = scoped_object(conn, "actions", payload.action_id, context["project"])
            if not action.get("published_at"):
                raise HTTPException(409, "Action 尚未填写实际发布时间，不能作为复测锚点")
            anchor = action["published_at"]
        try:
            anchor_at = parse_time(anchor)
            next_run = parse_time(payload.scheduled_at) if payload.scheduled_at else anchor_at + timedelta(days=payload.recurrence_days or 0)
        except (TypeError, ValueError) as error:
            raise HTTPException(400, "时间必须包含有效时区") from error
        if not payload.scheduled_at and not payload.recurrence_days:
            raise HTTPException(400, "一次性调度请填写执行时间；周期调度请选择 D7/D14/D28 或自定义天数")
        now = utc_now()
        schedule_id = conn.execute("INSERT INTO schedules(client_id,project_id,wave_id,scheduled_at,recurrence_days,next_run_at,anchor_at,action_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                   (context["project"]["client_id"], project_id, payload.wave_id, iso(next_run),
                                    payload.recurrence_days, iso(next_run), iso(anchor_at), payload.action_id, now, now)).lastrowid
        row = one(conn, "SELECT * FROM schedules WHERE id=?", (schedule_id,))
        audit(conn, context["user"]["id"], context["project"], "schedule", schedule_id, "create", None, row)
        return row


@router.put("/projects/{project_id}/schedules/{schedule_id}")
def update_schedule(project_id: int, schedule_id: int, payload: ScheduleUpdateIn, request: Request):
    context = require_admin(request, project_id)
    with transaction() as conn:
        old = scoped_object(conn, "schedules", schedule_id, context["project"])
        values = {"recurrence_days": old["recurrence_days"], "next_run_at": old["next_run_at"] or old["scheduled_at"],
                  "status": payload.status or old["status"]}
        if "recurrence_days" in payload.model_fields_set:
            values["recurrence_days"] = payload.recurrence_days
        if payload.scheduled_at:
            try:
                values["next_run_at"] = iso(parse_time(payload.scheduled_at))
            except ValueError as error:
                raise HTTPException(400, "执行时间格式不正确") from error
        if payload.status == "pending" and old["status"] in ("done", "cancelled") and not values["recurrence_days"] and not payload.scheduled_at:
            raise HTTPException(409, "已结束的一次性调度需要填写新的执行时间")
        conn.execute("UPDATE schedules SET recurrence_days=?,next_run_at=?,status=?,next_retry_at=NULL,last_error='',updated_at=? WHERE id=?",
                     (values["recurrence_days"], values["next_run_at"], values["status"], utc_now(), schedule_id))
        row = one(conn, "SELECT * FROM schedules WHERE id=?", (schedule_id,))
        audit(conn, context["user"]["id"], context["project"], "schedule", schedule_id, "update", old, row)
        return row


@router.get("/projects/{project_id}/alerts")
def alerts(project_id: int, request: Request, history: bool = False):
    context = project_context(request, project_id)
    with connect() as conn:
        condition = "" if history else "AND status='open'"
        return {"items": all_rows(conn, f"SELECT * FROM alerts WHERE project_id=? {condition} ORDER BY id DESC LIMIT 200", (project_id,))}


@router.post("/projects/{project_id}/alerts/{alert_id}/ack")
def acknowledge_alert(project_id: int, alert_id: int, request: Request):
    context = require_admin(request, project_id)
    with transaction() as conn:
        alert = scoped_object(conn, "alerts", alert_id, context["project"])
        conn.execute("UPDATE alerts SET status='acknowledged',acknowledged_by=?,acknowledged_at=?,updated_at=? WHERE id=?",
                     (context["user"]["id"], utc_now(), utc_now(), alert_id))
        audit(conn, context["user"]["id"], context["project"], "alert", alert_id, "acknowledge", alert,
              {"acknowledged_by": context["user"]["id"]})
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
    with transaction() as conn:
        log_id = conn.execute("INSERT INTO work_logs(client_id,project_id,user_id,hours,kind,note,work_date,created_at) VALUES(?,?,?,?,?,?,?,?)",
                              (context["project"]["client_id"], project_id, context["user"]["id"], payload.hours,
                               payload.kind, payload.note, payload.work_date or project_day(context["project"])[0], utc_now())).lastrowid
        row = one(conn, "SELECT * FROM work_logs WHERE id=?", (log_id,))
        audit(conn, context["user"]["id"], context["project"], "work_log", log_id, "create", None, row)
        return row


@router.get("/projects/{project_id}/operations")
def operations(project_id: int, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        summary = summarize_costs(conn, project_id)
        costs = summary["items"]
        queue = {row["status"]: row["count"] for row in conn.execute("SELECT status,COUNT(*) AS count FROM answers WHERE project_id=? GROUP BY status", (project_id,))}
        hours = one(conn, "SELECT COALESCE(SUM(hours),0) AS value FROM work_logs WHERE project_id=?", (project_id,))["value"]
        logs = all_rows(conn, "SELECT w.*,u.email FROM work_logs w LEFT JOIN users u ON u.id=w.user_id WHERE w.project_id=? ORDER BY w.id DESC LIMIT 100", (project_id,))
        return {"costs": costs, "cost_summary": {"by_currency": summary["by_currency"], "unknown": summary["unknown"],
                "tokens": summary["tokens"], "estimate_note": "按真实 usage 与管理员价格规则估算，非厂商账单"},
                "queue": queue, "work_hours": hours, "work_logs": logs,
                "db_bytes": config.db_path().stat().st_size if config.db_path().exists() else 0,
                "db_scope": "整个 SQLite 数据库，不是单项目占用"}


@router.get("/projects/{project_id}/retention/preview")
def retention_preview(project_id: int, request: Request):
    context = project_context(request, project_id, "analyst")
    with connect() as conn:
        return preview_retention(conn, context["project"])


@router.post("/projects/{project_id}/retention/execute")
def retention_execute(project_id: int, payload: RetentionIn, request: Request):
    context = require_admin(request, project_id)
    if not payload.confirm:
        raise HTTPException(409, "清理原始正文前必须确认预览结果")
    return execute_retention(context["project"], context["user"]["id"])


@router.post("/projects/{project_id}/backup")
def create_backup(project_id: int, request: Request):
    context = require_admin(request, project_id)
    started = utc_now()
    manifest = None
    failure = ""
    try:
        manifest = backup()
    except Exception as error:
        failure = f"{type(error).__name__}: {str(error)[:500]}"
    with transaction() as conn:
        status = "failed" if failure else "succeeded"
        conn.execute("INSERT INTO backup_runs(actor,client_id,project_id,status,manifest_json,error,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?)",
                     (context["user"]["id"], context["project"]["client_id"], project_id, status,
                      dumps(manifest or {}), failure, started, utc_now()))
        audit(conn, context["user"]["id"], context["project"], "database", project_id, "backup", None,
              manifest or {"status": status, "error": failure})
        if failure:
            conn.execute("INSERT INTO alerts(client_id,project_id,kind,severity,message,dedupe_key,created_at,updated_at) VALUES(?,?,'backup_failed','critical',?,?,?,?) ON CONFLICT DO NOTHING",
                         (context["project"]["client_id"], project_id, "数据库备份失败，请检查磁盘与备份目录后重试",
                          f"backup-failed:{project_id}", started, utc_now()))
        else:
            conn.execute("UPDATE alerts SET status='resolved',resolved_at=?,updated_at=? WHERE project_id=? AND dedupe_key=? AND status='open'",
                         (utc_now(), utc_now(), project_id, f"backup-failed:{project_id}"))
    if failure:
        raise HTTPException(500, "数据库备份失败，已记录告警与审计；请检查备份目录")
    return manifest


@router.get("/projects/{project_id}/export")
def export_project(project_id: int, request: Request):
    context = require_admin(request, project_id)
    with transaction() as conn:
        return build_project_export(conn, context["project"], context["user"]["id"])
