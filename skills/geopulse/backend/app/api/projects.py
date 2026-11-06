"""Client/project context and operations overview."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .. import config
from ..db import all_rows, connect, dumps, loads, one, utc_now
from ..security import audit, current_user, project_context, require_admin
from ..services.reporting import wave_metrics
from .schemas import ProjectIn, SettingsIn

router = APIRouter(prefix="/api", tags=["projects"])


def project_public(row: dict, role: str = "admin") -> dict:
    result = dict(row)
    settings = loads(result.pop("settings_json"), {})
    if role in ("reviewer", "viewer"):
        settings.pop("budget", None)
    result["settings"] = settings
    return result


@router.get("/projects")
def list_projects(request: Request):
    user = current_user(request)
    with connect() as conn:
        if user["global_role"] == "admin":
            rows = all_rows(conn, "SELECT p.*,c.name AS client_name,'admin' AS member_role FROM projects p JOIN clients c ON c.id=p.client_id ORDER BY p.id DESC")
        else:
            rows = all_rows(conn, "SELECT p.*,c.name AS client_name,m.role AS member_role FROM projects p JOIN clients c ON c.id=p.client_id JOIN memberships m ON m.project_id=p.id AND m.user_id=? ORDER BY p.id DESC", (user["id"],))
    return {"items": [project_public(row, row["member_role"]) for row in rows]}


@router.post("/projects")
def create_project(payload: ProjectIn, request: Request):
    user = current_user(request)
    if user["global_role"] != "admin":
        raise HTTPException(403, "只有管理员可以创建项目")
    with connect() as conn:
        client = one(conn, "SELECT * FROM clients WHERE name=?", (payload.client_name.strip(),))
        client_id = client["id"] if client else conn.execute("INSERT INTO clients(name,created_at) VALUES(?,?)",
                                                             (payload.client_name.strip(), utc_now())).lastrowid
        project_id = conn.execute("INSERT INTO projects(client_id,name,category,market,language,timezone,service_package,settings_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                  (client_id, payload.name.strip(), payload.category.strip(), payload.market,
                                   payload.language, payload.timezone, payload.service_package,
                                   dumps(config.DEFAULT_PROJECT_SETTINGS), utc_now())).lastrowid
        conn.execute("INSERT INTO memberships(client_id,project_id,user_id,role,created_at) VALUES(?,?,?,'admin',?)",
                     (client_id, project_id, user["id"], utc_now()))
        conn.execute("INSERT INTO engine_configs(client_id,project_id,name,vendor,kind,mode,created_at) VALUES(?,?,?,'GeoPulse','demo','memory',?)",
                     (client_id, project_id, "demo", utc_now()))
        row = one(conn, "SELECT * FROM projects WHERE id=?", (project_id,))
        audit(conn, user["id"], row, "project", project_id, "create", None, row)
        conn.commit()
    return project_public(row)


@router.get("/projects/{project_id}")
def get_project(project_id: int, request: Request):
    context = project_context(request, project_id)
    return project_public(context["project"], context["role"])


@router.put("/projects/{project_id}/settings")
def update_settings(project_id: int, payload: SettingsIn, request: Request):
    context = require_admin(request, project_id)
    allowed = {"confidence_level", "small_sample_n", "min_pair_completeness", "repeats", "score_weights",
               "source_domains", "budget", "retention_days", "prompt_quotas", "alert_delta_pp"}
    if set(payload.settings) - allowed:
        raise HTTPException(400, "包含不支持的设置字段")
    settings = {**loads(context["project"]["settings_json"], {}), **payload.settings}
    budget = settings.get("budget") or {}
    if not isinstance(budget, dict):
        raise HTTPException(400, "预算设置格式不正确")
    for key in ("amount", "wave_amount", "daily_amount"):
        if budget.get(key) is not None and float(budget[key]) < 0:
            raise HTTPException(400, "预算额度不能为负数")
    currency = str(budget.get("currency") or "CNY")
    if len(currency) != 3 or not currency.isalpha():
        raise HTTPException(400, "预算币种必须是三位货币代码")
    budget["currency"] = currency.upper()
    if not 0.5 <= float(settings.get("min_pair_completeness", 0.9)) <= 1:
        raise HTTPException(400, "配对完整度必须在 50%–100%")
    retention_days = settings.get("retention_days")
    if retention_days not in (None, "", 0, "0"):
        try:
            if int(retention_days) < 1:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise HTTPException(400, "保留天数必须为正整数；空值或 0 表示不自动清理") from error
    with connect() as conn:
        conn.execute("UPDATE projects SET settings_json=? WHERE id=?", (dumps(settings), project_id))
        audit(conn, context["user"]["id"], context["project"], "project", project_id, "settings",
              context["project"]["settings_json"], settings)
        conn.commit()
    return {"settings": settings}


@router.get("/projects/{project_id}/overview")
def overview(project_id: int, request: Request):
    context = project_context(request, project_id)
    with connect() as conn:
        counts = {}
        for table, status_field in (("brand_entities", "status"), ("prompt_sets", "status"),
                                    ("opportunities", "status"), ("actions", "status"), ("reports", "approval_status")):
            counts[table] = {row[status_field]: row["count"] for row in conn.execute(
                f"SELECT {status_field},COUNT(*) AS count FROM {table} WHERE project_id=? GROUP BY {status_field}", (project_id,))}
        waves = all_rows(conn, "SELECT id,label,status,official_run_id,created_at FROM waves WHERE project_id=? ORDER BY id DESC LIMIT 8", (project_id,))
        next_schedule = one(conn, "SELECT * FROM schedules WHERE project_id=? AND status='pending' ORDER BY scheduled_at LIMIT 1", (project_id,))
        failed = one(conn, "SELECT COUNT(*) AS count FROM answers WHERE project_id=? AND status='failed'", (project_id,))["count"]
        alerts = all_rows(conn, "SELECT * FROM alerts WHERE project_id=? AND status='open' ORDER BY id DESC LIMIT 5", (project_id,))
        work = one(conn, "SELECT COALESCE(SUM(hours),0) AS hours FROM work_logs WHERE project_id=?", (project_id,))["hours"]
        latest_metrics = None
        official = one(conn, "SELECT * FROM waves WHERE project_id=? AND official_run_id IS NOT NULL ORDER BY id DESC LIMIT 1", (project_id,))
        if official:
            metrics, _, _ = wave_metrics(conn, official)
            latest_metrics = {key: value for key, value in metrics.items() if key != "pairs"}
        costs = one(conn, "SELECT SUM(c.cost) AS amount,COUNT(c.id) AS calls FROM call_attempts c JOIN answers a ON a.id=c.answer_id WHERE a.project_id=?", (project_id,))
        stage = "诊断准备"
        if counts["prompt_sets"].get("frozen"):
            stage = "基线测量"
        if official:
            stage = "机会执行"
        if counts["actions"].get("published") or counts["actions"].get("remeasure_due"):
            stage = "效果复测"
        todos = []
        if counts["brand_entities"].get("pending_review") or counts["brand_entities"].get("draft"):
            todos.append({"kind": "entities", "label": "审核品牌实体与开放候选", "count": counts["brand_entities"].get("pending_review", 0) + counts["brand_entities"].get("draft", 0)})
        if counts["opportunities"].get("candidate") or counts["opportunities"].get("eligibility_pending"):
            todos.append({"kind": "opportunities", "label": "确认候选机会适用性", "count": counts["opportunities"].get("candidate", 0) + counts["opportunities"].get("eligibility_pending", 0)})
        if counts["reports"].get("draft") or counts["reports"].get("data_checked") or counts["reports"].get("strategy_reviewed"):
            todos.append({"kind": "reports", "label": "完成报告审批", "count": sum(counts["reports"].get(key, 0) for key in ("draft", "data_checked", "strategy_reviewed"))})
        return {"stage": stage, "counts": counts, "waves": waves, "next_schedule": next_schedule,
                "failed_samples": failed, "alerts": alerts, "latest_metrics": latest_metrics,
                "work_hours": work, "role": context["role"],
                "operations": {"external_calls": costs["calls"], "actual_cost": costs["amount"] if context["role"] in ("admin", "analyst") else None},
                "todos": todos}


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, confirm: str, request: Request):
    context = require_admin(request, project_id)
    if confirm != context["project"]["name"]:
        raise HTTPException(400, "确认文本必须与项目名完全一致")
    with connect() as conn:
        audit(conn, context["user"]["id"], context["project"], "project", project_id, "delete", context["project"], None)
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
        conn.execute("DELETE FROM clients WHERE id=? AND NOT EXISTS(SELECT 1 FROM projects WHERE client_id=?)",
                     (context["project"]["client_id"], context["project"]["client_id"]))
        conn.commit()
    return {"deleted": project_id, "audit": "已记录项目删除事件"}
