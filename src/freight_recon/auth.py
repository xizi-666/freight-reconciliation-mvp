"""Small single-process, server-side sessions carried in HttpOnly cookies."""
import hashlib
import hmac
import os
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from .db import SessionLocal, User, hash_password

router = APIRouter(prefix="/api", tags=["用户登录"])
COOKIE_NAME = "freight_session"
SESSION_TTL = 8 * 60 * 60
# Intentionally process-local: restart logs users out. No role is trusted from cookies.
_sessions: dict[str, tuple[int, float]] = {}


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


def public_user(user: User) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role, "is_active": user.is_active}


def session_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def resolve_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    key = session_digest(token)
    entry = _sessions.get(key)
    if entry is None:
        return None
    user_id, expiry = entry
    if expiry <= time.time():
        _sessions.pop(key, None)
        return None
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        return public_user(user) if user and user.is_active else None


async def get_current_user(request: Request) -> dict:
    user = getattr(request.state, "user", None) or await resolve_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def require_role(role: str):
    async def dependency(user: dict = Depends(get_current_user)):
        if user["role"] != role:
            raise HTTPException(status_code=403, detail="当前角色无权执行此操作")
        return user
    return dependency


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.username == body.username.strip()))
        actual_hash = user.password_hash if user else "0" * 64
        password_ok = hmac.compare_digest(actual_hash, hash_password(body.password))
        if not user or not password_ok or not user.is_active:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        result = public_user(user)
    # Rotate any previous session and discard expired entries.
    old = request.cookies.get(COOKIE_NAME)
    if old:
        _sessions.pop(session_digest(old), None)
    now = time.time()
    for key, (_user_id, expiry) in list(_sessions.items()):
        if expiry <= now:
            _sessions.pop(key, None)
    token = secrets.token_urlsafe(32)
    _sessions[session_digest(token)] = (result["id"], now + SESSION_TTL)
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_TTL, httponly=True,
                        samesite="lax", secure=os.getenv("FREIGHT_COOKIE_SECURE", "0") == "1", path="/")
    return {"user": result}


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        _sessions.pop(session_digest(token), None)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"message": "已退出登录"}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return user
