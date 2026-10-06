"""Account sessions for the PWA. No password or session token is kept in the browser UI."""

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database import SessionLocal
from models import User, UserCredential, UserSession


_user_id = ContextVar("radar_user_id", default=None)
_attempts = {}
_attempts_lock = threading.Lock()
SESSION_DAYS = 14


def current_user_id():
    return _user_id.get()


def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**15, r=8, p=3,
                            maxmem=64 * 1024 * 1024)
    return f"scrypt$32768$8$3${salt.hex()}${digest.hex()}"


def verify_password(password, encoded):
    try:
        algorithm, n, r, p, salt, stored = encoded.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                                n=int(n), r=int(r), p=int(p), maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(digest, bytes.fromhex(stored))
    except (ValueError, OverflowError):
        return False


def _cookie_name(request):
    host = request.url.hostname
    local = host in {"127.0.0.1", "localhost", "testserver"}
    if local and (getattr(request.app.state, "auth_insecure_local_cookie", False) or
                  os.getenv("RADAR_ALLOW_HTTP_LOCAL") == "1"):
        return "radar_local_session", False
    return "__Host-radar_session", True


def _session_from_request(request, db):
    cookie, _ = _cookie_name(request)
    token = request.cookies.get(cookie)
    if not token:
        return None
    row = db.scalar(select(UserSession).where(
        UserSession.token_hash == hashlib.sha256(token.encode("utf-8")).hexdigest()))
    if row is None:
        return None
    expiry = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
    return row if expiry > datetime.now(timezone.utc) else None


def _session_factory(app):
    return getattr(app.state, "auth_session_factory", SessionLocal)


def _issue_session(request, db, user, status_code=200):
    previous = _session_from_request(request, db)
    if previous is not None:
        db.delete(previous)
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    db.add(UserSession(user_id=user.id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                       csrf_token=csrf, expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)))
    db.commit()
    cookie, secure = _cookie_name(request)
    response = JSONResponse({"username": user.username, "csrf_token": csrf}, status_code=status_code)
    response.set_cookie(cookie, token, max_age=SESSION_DAYS * 86400, path="/",
                        secure=secure, httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return response


def _origin_ok(request):
    origin = request.headers.get("origin")
    expected = os.getenv("RADAR_PUBLIC_ORIGIN") or str(request.base_url).rstrip("/")
    return origin is None or hmac.compare_digest(origin, expected)


def _limited(request, kind="login"):
    address = (request.client.host if request.client else "unknown", kind)
    now = time.monotonic()
    with _attempts_lock:
        attempts = [stamp for stamp in _attempts.get(address, []) if now - stamp < 600]
        _attempts[address] = attempts
        return len(attempts) >= 10


def _record_failure(request, kind="login"):
    address = (request.client.host if request.client else "unknown", kind)
    with _attempts_lock:
        _attempts.setdefault(address, []).append(time.monotonic())


def _clear_failures(request):
    address = (request.client.host if request.client else "unknown", "login")
    with _attempts_lock:
        _attempts.pop(address, None)


class AccountInput(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=12, max_length=128)


def install_auth(app, get_db):
    @app.middleware("http")
    async def protect_api(request: Request, call_next):
        path = request.url.path
        method = request.method
        worker_path = (path.startswith("/api/internal/") or
                       (method not in {"GET", "HEAD", "OPTIONS"} and
                        (path.startswith("/api/news/") or path.endswith("/news/analyze-all") or
                         (path.startswith("/api/assets") and path != "/api/assets/quick" and
                          (path == "/api/assets" or method in {"PATCH", "DELETE"})))))
        if worker_path:
            configured = os.getenv("RADAR_WORKER_TOKEN", "")
            supplied = request.headers.get("x-radar-worker-token", "")
            if not configured:
                return JSONResponse({"detail": "News worker token is not configured"}, status_code=503)
            if not hmac.compare_digest(configured, supplied):
                return JSONResponse({"detail": "Forbidden"}, status_code=403)
            return await call_next(request)
        public_auth = path in {"/api/auth/login", "/api/auth/register"}
        private_read = path.startswith(("/api/watchlist", "/api/alert-rules", "/api/notifications",
                                        "/api/client-profile", "/api/client-assets"))
        guarded = path.startswith("/api/") and ((method not in {"GET", "HEAD", "OPTIONS"} and not public_auth) or private_read)
        if public_auth and not _origin_ok(request):
            return JSONResponse({"detail": "Invalid request origin"}, status_code=403)
        if not guarded:
            return await call_next(request)
        with _session_factory(app)() as db:
            session = _session_from_request(request, db)
            if session is None:
                return JSONResponse({"detail": "请先登录"}, status_code=401, headers={"Cache-Control": "no-store"})
            user_id = session.user_id
            if method not in {"GET", "HEAD", "OPTIONS"}:
                csrf = request.headers.get("x-csrf-token", "")
                if not _origin_ok(request) or not hmac.compare_digest(csrf, session.csrf_token):
                    return JSONResponse({"detail": "登录验证已失效，请刷新页面"}, status_code=403)
        token = _user_id.set(user_id)
        try:
            response = await call_next(request)
            if private_read:
                response.headers["Cache-Control"] = "no-store"
            return response
        finally:
            _user_id.reset(token)

    @app.post("/api/auth/register", status_code=201)
    def register(payload: AccountInput, request: Request, db=Depends(get_db)):
        if _limited(request, "register"):
            raise HTTPException(status_code=429, detail="尝试过于频繁，请稍后再试")
        username = payload.username.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{3,32}", username):
            raise HTTPException(status_code=422, detail="用户名只能包含英文字母、数字和下划线")
        if db.scalar(select(User.id).where(User.username == username)) is not None:
            _record_failure(request, "register")
            raise HTTPException(status_code=409, detail="用户名已被使用")
        user = User(username=username)
        db.add(user)
        try:
            db.flush()
            db.add(UserCredential(user_id=user.id, password_hash=password_hash(payload.password)))
            response = _issue_session(request, db, user, status_code=201)
        except IntegrityError:
            db.rollback()
            _record_failure(request, "register")
            raise HTTPException(status_code=409, detail="用户名已被使用")
        _record_failure(request, "register")  # Bound open account creation per client address.
        return response

    @app.post("/api/auth/login")
    def login(payload: AccountInput, request: Request, db=Depends(get_db)):
        if _limited(request):
            raise HTTPException(status_code=429, detail="尝试过于频繁，请稍后再试")
        user = db.scalar(select(User).where(User.username == payload.username.strip().lower()))
        credential = db.get(UserCredential, user.id) if user else None
        if credential is None or not verify_password(payload.password, credential.password_hash):
            _record_failure(request)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        _clear_failures(request)
        return _issue_session(request, db, user)

    @app.get("/api/auth/session")
    def session_info(request: Request, db=Depends(get_db)):
        session = _session_from_request(request, db)
        if session is None:
            raise HTTPException(status_code=401, detail="请先登录")
        user = db.get(User, session.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="请先登录")
        return JSONResponse({"username": user.username, "csrf_token": session.csrf_token},
                            headers={"Cache-Control": "no-store"})

    @app.post("/api/auth/logout")
    def logout(request: Request, db=Depends(get_db)):
        session = _session_from_request(request, db)
        if session is not None:
            db.delete(session)
            db.commit()
        response = JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
        cookie, _ = _cookie_name(request)
        response.delete_cookie(cookie, path="/")
        return response


def authenticated_websocket(websocket):
    with _session_factory(websocket.app)() as db:
        return _session_from_request(websocket, db) is not None
