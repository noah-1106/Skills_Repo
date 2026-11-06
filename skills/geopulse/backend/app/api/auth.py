"""Authentication routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from ..db import connect, one, utc_now
from .. import config
from ..security import COOKIE_NAME, create_session, current_user, hash_password, user_payload, verify_password
from .schemas import LoginIn, PasswordIn

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginIn, response: Response, request: Request):
    with connect() as conn:
        user = one(conn, "SELECT * FROM users WHERE email=? COLLATE NOCASE AND status='active'", (payload.email.strip(),))
        if not user or not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(401, "邮箱或密码不正确")
    session = create_session(user["id"])
    response.set_cookie(COOKIE_NAME, session["token"], httponly=True, secure=request.url.scheme == "https",
                        samesite="strict", max_age=config.session_hours() * 3600, path="/")
    request.state.session = {"csrf_token": session["csrf_token"]}
    public = {key: user[key] for key in ("id", "email", "global_role", "status", "created_at")}
    return {**user_payload(public, request), "access_token": session["token"], "token_type": "bearer"}


@router.get("/me")
def me(request: Request):
    return user_payload(current_user(request), request)


@router.post("/logout")
def logout(request: Request, response: Response):
    current_user(request)
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (request.state.session["token_hash"],))
        conn.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/password")
def change_password(payload: PasswordIn, request: Request):
    user = current_user(request)
    with connect() as conn:
        row = one(conn, "SELECT password_hash FROM users WHERE id=?", (user["id"],))
        if not verify_password(payload.current_password, row["password_hash"]):
            raise HTTPException(400, "当前密码不正确")
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(payload.new_password), user["id"]))
        conn.execute("DELETE FROM sessions WHERE user_id=? AND token_hash!=?", (user["id"], request.state.session["token_hash"]))
        conn.commit()
    return {"ok": True}
