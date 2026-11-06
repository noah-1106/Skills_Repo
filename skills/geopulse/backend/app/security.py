"""Authentication, project authorization, CSRF and secret storage."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from . import config
from .db import connect, dumps, loads, one, utc_now

COOKIE_NAME = "gp_session"
ROLE_RANK = {"viewer": 1, "reviewer": 2, "analyst": 3, "admin": 4}


def hash_password(password: str, salt: bytes | None = None) -> str:
    if len(password) < 10:
        raise ValueError("密码至少 10 个字符")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, rounds, salt, expected = encoded.split("$", 3)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id: int) -> dict:
    token = secrets.token_urlsafe(40)
    csrf = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at<=?", (now.isoformat(),))
        conn.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)",
                     (_token_hash(token), user_id, csrf,
                      (now + timedelta(hours=config.session_hours())).isoformat(), now.isoformat()))
        conn.commit()
    return {"token": token, "csrf_token": csrf}


def current_user(request: Request) -> dict:
    cookie = request.cookies.get(COOKIE_NAME)
    bearer = request.headers.get("Authorization", "")
    token = cookie or (bearer.removeprefix("Bearer ") if bearer.startswith("Bearer ") else "")
    if not token:
        raise HTTPException(401, "请先登录")
    with connect() as conn:
        session = one(conn, "SELECT * FROM sessions WHERE token_hash=?", (_token_hash(token),))
        if not session or session["expires_at"] <= datetime.now(timezone.utc).isoformat():
            raise HTTPException(401, "登录已过期，请重新登录")
        user = one(conn, "SELECT id,email,global_role,status,created_at FROM users WHERE id=? AND status='active'",
                   (session["user_id"],))
        if not user:
            raise HTTPException(401, "账号不可用")
    if cookie and request.method not in ("GET", "HEAD", "OPTIONS"):
        supplied = request.headers.get("X-CSRF-Token", "")
        if not supplied or not hmac.compare_digest(supplied, session["csrf_token"]):
            raise HTTPException(403, "安全令牌无效，请刷新页面后重试")
    request.state.session = session
    request.state.user = user
    request.state.auth_via_cookie = bool(cookie)
    return user


def project_context(request: Request, project_id: int, minimum_role: str = "viewer") -> dict:
    user = current_user(request)
    with connect() as conn:
        project = one(conn, "SELECT * FROM projects WHERE id=?", (project_id,))
        if not project:
            raise HTTPException(404, "项目不存在")
        if user["global_role"] == "admin":
            role = "admin"
        else:
            membership = one(conn, "SELECT role FROM memberships WHERE project_id=? AND user_id=?",
                             (project_id, user["id"]))
            if not membership:
                raise HTTPException(403, "你没有访问该项目的权限")
            role = membership["role"]
    if ROLE_RANK[role] < ROLE_RANK[minimum_role]:
        raise HTTPException(403, f"该操作需要{minimum_role}权限")
    return {"user": user, "role": role, "project": project,
            "client_id": project["client_id"], "project_id": project_id}


def require_admin(request: Request, project_id: int) -> dict:
    return project_context(request, project_id, "admin")


def redact(value: Any) -> Any:
    sensitive = ("api_key", "password", "secret", "authorization", "token")
    if isinstance(value, dict):
        return {k: ("***" if any(s in k.lower() for s in sensitive) else redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def audit(conn, actor: int | None, project: dict | None, object_type: str, object_id: Any,
          action: str, before: Any = None, after: Any = None) -> None:
    project_id = (project.get("project_id") if "project_id" in project else project.get("id")) if project else None
    conn.execute("INSERT INTO audit_events(actor,client_id,project_id,object_type,object_id,action,before_json,after_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                 (actor, project.get("client_id") if project else None,
                  project_id, object_type, str(object_id), action,
                  dumps(redact(before)) if before is not None else None,
                  dumps(redact(after)) if after is not None else None, utc_now()))


class SecretStore:
    def __init__(self, path: Path | None = None):
        self.path = path or config.secret_path()

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def put(self, value: str, reference: str | None = None) -> str:
        if not value:
            return ""
        reference = reference or f"sec_{uuid.uuid4().hex}"
        data = self._read()
        data[reference] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.chmod(0o600)
        temp.replace(self.path)
        self.path.chmod(0o600)
        return reference

    def get(self, reference: str) -> str:
        return self._read().get(reference, "") if reference else ""

    def delete(self, reference: str) -> None:
        data = self._read()
        if reference in data:
            del data[reference]
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self.path.chmod(0o600)


def user_payload(user: dict, request: Request) -> dict:
    return {"user": user, "csrf_token": request.state.session["csrf_token"]}
