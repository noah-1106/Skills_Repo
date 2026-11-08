"""Admin-managed browser session metadata and collection recovery."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import HTTPException

from .. import config
from ..collectors import get_driver
from ..db import all_rows, one, utc_now
from ..security import audit
from . import web_collection


def public(row: dict) -> dict:
    return {key: row.get(key) for key in (
        "id", "project_id", "engine_config_id", "driver", "status", "verification_requested",
        "authorized_at", "last_verified_at", "worker_heartbeat_at", "last_error",
        "created_at", "updated_at", "revoked_at",
    )}


def profile_path(reference: str) -> Path:
    if not re.fullmatch(r"profile_[a-f0-9]{32}", reference or ""):
        raise ValueError("浏览器 profile reference 无效")
    return config.browser_profile_dir() / reference


def get(conn, project: dict, session_id: int) -> dict:
    row = one(conn, "SELECT * FROM browser_sessions WHERE id=? AND project_id=? AND client_id=?",
              (session_id, project["id"], project["client_id"]))
    if not row:
        raise HTTPException(404, "浏览器会话不存在或不属于当前项目")
    return row


def list_for_engine(conn, project: dict, engine_id: int) -> list[dict]:
    return [public(row) for row in all_rows(conn, """SELECT * FROM browser_sessions
                                                   WHERE project_id=? AND engine_config_id=?
                                                   ORDER BY id DESC""", (project["id"], engine_id))]


def create(conn, project: dict, engine_id: int, driver_key: str, actor: int) -> dict:
    engine = one(conn, "SELECT * FROM engine_configs WHERE id=? AND project_id=? AND client_id=?",
                 (engine_id, project["id"], project["client_id"]))
    if not engine or engine["kind"] != "manual_web" or not engine["enabled"]:
        raise HTTPException(404, "Consumer Web 目标不存在、已停用或不属于当前项目")
    get_driver(driver_key)
    existing = one(conn, """SELECT id,status FROM browser_sessions
                           WHERE engine_config_id=? AND driver=? AND status IN ('pending','active')
                           ORDER BY id DESC LIMIT 1""", (engine_id, driver_key))
    if existing:
        raise HTTPException(409, "该目标已有待验证或可用会话；请先验证，或在连接管理中撤销后重新创建")
    now = utc_now()
    reference = f"profile_{uuid.uuid4().hex}"
    path = profile_path(reference)
    path.mkdir(parents=False, exist_ok=False, mode=0o700)
    path.chmod(0o700)
    session_id = conn.execute("""INSERT INTO browser_sessions(
        client_id,project_id,engine_config_id,driver,profile_ref,status,authorized_by,authorized_at,created_at,updated_at)
        VALUES(?,?,?,?,?,'pending',?,?,?,?)""",
        (project["client_id"], project["id"], engine_id, driver_key, reference, actor, now, now, now)).lastrowid
    audit(conn, actor, project, "browser_session", session_id, "authorize", None,
          {"engine_config_id": engine_id, "driver": driver_key, "status": "pending"})
    return public(get(conn, project, session_id))


def request_verification(conn, project: dict, session_id: int, actor: int) -> dict:
    row = get(conn, project, session_id)
    if row["status"] == "revoked":
        raise HTTPException(409, "会话已撤销，请重新创建连接")
    conn.execute("""UPDATE browser_sessions SET verification_requested=1,last_error='',updated_at=?
                    WHERE id=?""", (utc_now(), session_id))
    audit(conn, actor, project, "browser_session", session_id, "verify_requested", None,
          {"driver": row["driver"]})
    return public(get(conn, project, session_id))


def revoke(conn, project: dict, session_id: int, actor: int) -> dict:
    row = get(conn, project, session_id)
    if row["status"] != "revoked":
        now = utc_now()
        conn.execute("""UPDATE browser_sessions SET status='revoked',verification_requested=0,
                        revoked_at=?,updated_at=? WHERE id=?""", (now, now, session_id))
        audit(conn, actor, project, "browser_session", session_id, "revoke",
              {"status": row["status"]}, {"status": "revoked"})
    return public(get(conn, project, session_id))


def resume_collection(conn, project: dict, answer_id: int, payload: dict, actor: int) -> dict:
    answer = one(conn, "SELECT * FROM answers WHERE id=? AND project_id=? AND client_id=?",
                 (answer_id, project["id"], project["client_id"]))
    if not answer:
        raise HTTPException(404, "回答不存在或不属于当前项目")
    collection = one(conn, "SELECT * FROM web_collections WHERE answer_id=?", (answer_id,))
    if not collection or collection.get("collection_method") != "browser_assisted":
        raise HTTPException(409, "该回答不是授权浏览器采集任务")
    if answer["status"] != "awaiting_collection" or collection["browser_phase"] not in ("awaiting_user", "paused_unknown"):
        raise HTTPException(409, "当前采集状态不需要人工恢复")
    if payload.get("action") == "fail":
        return web_collection.fail_collection(conn, project, answer_id, {
            "failure_type": "other",
            "failure_detail": payload.get("detail") or "管理员确认无法可靠恢复网页回答；未形成有效样本",
            "notes": "授权浏览器采集结果不明，未自动重发问题",
        }, actor)
    if collection.get("browser_send_started_at") and not collection.get("conversation_url"):
        raise HTTPException(409, "问题可能已发送但没有可核对的会话 URL；只能登记失败，不能自动重发")
    session = get(conn, project, int(collection.get("browser_session_id") or 0))
    if session["status"] != "active":
        raise HTTPException(409, "请先完成本机浏览器登录验证，再恢复当前采集")
    detail = "仅恢复原会话，禁止重发问题" if collection.get("browser_send_started_at") else "用户已处理登录/验证码，继续采集"
    conn.execute("""UPDATE web_collections SET browser_phase='queued',browser_lease_owner='',
                    browser_lease_expires_at=NULL,browser_heartbeat_at=NULL,browser_phase_detail=?,updated_at=?
                    WHERE id=?""", (detail, utc_now(), collection["id"]))
    audit(conn, actor, project, "web_collection", collection["id"], "browser_resume", None,
          {"answer_id": answer_id, "prompt_already_sent": bool(collection.get("browser_send_started_at"))})
    return web_collection.get_collection(conn, project, answer_id)
