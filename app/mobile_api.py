"""Account-scoped endpoints for the mobile client."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
import threading
import time
from pathlib import Path

from fastapi import Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from models import AlertRule, Asset, Notification, TelegramChallenge, User, UserHiddenAsset, WatchlistItem
from crypto_metrics import get_futures_metrics
from telegram_service import BOT_TOKEN, CHAT_ID, get_bot_username, send_telegram_message

_telegram_test_times = {}
_telegram_test_lock = threading.Lock()


class TelegramTarget(BaseModel):
    chat_id: str = Field(min_length=5, max_length=20)


class TelegramCode(BaseModel):
    code: str = Field(min_length=8, max_length=8)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def install_mobile_routes(app, get_db, get_default_user, read_binance_json):
    web = Path(__file__).resolve().parent / "web"

    @app.get("/legacy", include_in_schema=False)
    def legacy():
        return FileResponse(web / "index.html")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        return FileResponse(
            web / "sw.js", media_type="application/javascript",
            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
        )

    @app.get("/api/client-profile")
    def client_profile(db=Depends(get_db)):
        user = get_default_user(db)
        mode = "personal" if user.telegram_chat_id else "legacy" if user.username == "default" and CHAT_ID else "none"
        return {
            "username": user.username,
            "created_at": user.created_at,
            "mode": "account",
            "telegram_configured": mode != "none",
            "telegram_mode": mode,
            "telegram_bot_available": bool(BOT_TOKEN),
            "capabilities": {
                "authentication": True, "registration": True,
                "crypto_metrics": True, "push_notifications": False,
            },
        }

    @app.get("/api/client-assets/hidden")
    def hidden_assets(db=Depends(get_db)):
        user = get_default_user(db)
        return list(db.scalars(select(UserHiddenAsset.asset_id).where(
            UserHiddenAsset.user_id == user.id)).all())

    @app.get("/api/client-profile/telegram/bot")
    def telegram_bot():
        username = get_bot_username()
        return {"username": username, "url": f"https://t.me/{username}" if username else None}

    @app.get("/api/client-version")
    def client_version():
        from fastapi.responses import JSONResponse
        version = (web / "version.txt").read_text(encoding="utf-8").strip()
        return JSONResponse({"version": version}, headers={"Cache-Control": "no-store"})

    @app.put("/api/client-assets/{asset_id}/hidden")
    def hide_asset(asset_id: int, db=Depends(get_db)):
        user = get_default_user(db)
        if db.get(Asset, asset_id) is None:
            raise HTTPException(status_code=404, detail="资产不存在")
        hidden = db.scalar(select(UserHiddenAsset).where(
            UserHiddenAsset.user_id == user.id, UserHiddenAsset.asset_id == asset_id))
        if hidden is None:
            db.add(UserHiddenAsset(user_id=user.id, asset_id=asset_id))
        watched = db.scalar(select(WatchlistItem).where(
            WatchlistItem.user_id == user.id, WatchlistItem.asset_id == asset_id))
        if watched is not None:
            db.delete(watched)
        for rule in db.scalars(select(AlertRule).where(
                AlertRule.user_id == user.id, AlertRule.asset_id == asset_id)).all():
            rule.enabled = False
        db.commit()
        return {"hidden": True, "asset_id": asset_id}

    @app.delete("/api/client-assets/{asset_id}/hidden")
    def restore_asset(asset_id: int, db=Depends(get_db)):
        user = get_default_user(db)
        hidden = db.scalar(select(UserHiddenAsset).where(
            UserHiddenAsset.user_id == user.id, UserHiddenAsset.asset_id == asset_id))
        if hidden is not None:
            db.delete(hidden)
            db.commit()
        return {"hidden": False, "asset_id": asset_id}

    @app.post("/api/client-profile/telegram/challenge")
    def telegram_challenge(payload: TelegramTarget, db=Depends(get_db)):
        user = get_default_user(db)
        chat_id = payload.chat_id.strip()
        if not re.fullmatch(r"-?[0-9]{5,20}", chat_id):
            raise HTTPException(status_code=400, detail="请输入有效的数字 Telegram Chat ID")
        if not BOT_TOKEN:
            raise HTTPException(status_code=503, detail="服务器尚未配置 Telegram Bot")
        now = datetime.now(timezone.utc)
        current = db.get(TelegramChallenge, user.id)
        if current is not None and now - aware(current.created_at) < timedelta(seconds=60):
            raise HTTPException(status_code=429, detail="请等待一分钟后再发送验证码")
        code = secrets.token_hex(4)
        if not send_telegram_message(f"MIRAO 绑定验证码：{code}。10 分钟内在网站输入。", chat_id=chat_id):
            raise HTTPException(status_code=502, detail="Telegram 发送失败。请先向你的 Bot 发送 /start，并核对 Chat ID。")
        digest = hashlib.sha256(f"{user.id}:{chat_id}:{code}".encode()).hexdigest()
        if current is None:
            db.add(TelegramChallenge(user_id=user.id, chat_id=chat_id, code_hash=digest,
                                     created_at=now, expires_at=now + timedelta(minutes=10), attempts=0))
        else:
            current.chat_id = chat_id
            current.code_hash = digest
            current.created_at = now
            current.expires_at = now + timedelta(minutes=10)
            current.attempts = 0
        db.commit()
        return {"sent": True, "expires_in_seconds": 600}

    @app.post("/api/client-profile/telegram/confirm")
    def confirm_telegram(payload: TelegramCode, db=Depends(get_db)):
        user = get_default_user(db)
        challenge = db.get(TelegramChallenge, user.id)
        now = datetime.now(timezone.utc)
        if challenge is None or aware(challenge.expires_at) <= now or challenge.attempts >= 5:
            raise HTTPException(status_code=400, detail="验证码已过期，请重新发送")
        digest = hashlib.sha256(f"{user.id}:{challenge.chat_id}:{payload.code.strip().lower()}".encode()).hexdigest()
        if not hmac.compare_digest(digest, challenge.code_hash):
            challenge.attempts += 1
            db.commit()
            raise HTTPException(status_code=400, detail="验证码不正确")
        user.telegram_chat_id = challenge.chat_id
        db.delete(challenge)
        db.commit()
        return {"telegram_configured": True}

    @app.post("/api/client-profile/telegram/test")
    def test_telegram(db=Depends(get_db)):
        user = get_default_user(db)
        target = user.telegram_chat_id or (CHAT_ID if user.username == "default" else None)
        if not target:
            raise HTTPException(status_code=400, detail="请先绑定 Telegram 接收目标")
        if not BOT_TOKEN:
            raise HTTPException(status_code=503, detail="服务器尚未配置 Telegram Bot")
        now = time.monotonic()
        with _telegram_test_lock:
            if now - _telegram_test_times.get(user.id, -1e10) < 60:
                raise HTTPException(status_code=429, detail="测试消息每分钟最多发送一次")
            _telegram_test_times[user.id] = now
        if not send_telegram_message("MIRAO 测试消息：Telegram 接收目标已连通。", chat_id=target):
            raise HTTPException(status_code=502, detail="测试消息发送失败，请检查 Bot 和目标会话")
        return {"sent": True}

    @app.get("/api/notifications")
    def notifications(
        limit: int = Query(default=50, ge=1, le=200),
        before_id: int | None = Query(default=None, ge=1),
        db=Depends(get_db),
    ):
        user = get_default_user(db)
        query = select(Notification).where(Notification.user_id == user.id)
        if before_id is not None:
            query = query.where(Notification.id < before_id)
        rows = db.scalars(query.order_by(Notification.id.desc()).limit(limit)).all()
        return [{
            "id": row.id, "asset_id": row.asset_id,
            "category": row.category, "title": row.title, "message": row.message,
            "channel": row.channel, "status": row.status,
            "created_at": row.created_at, "sent_at": row.sent_at,
        } for row in rows]

    @app.get("/api/assets/{asset_id}/crypto-metrics")
    def crypto_metrics(asset_id: int, db=Depends(get_db)):
        asset = db.get(Asset, asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="Asset not found")
        return get_futures_metrics(asset, read_binance_json)

    @app.get("/api/internal/news-watchlist")
    def news_worker_watchlist(db=Depends(get_db)):
        rows = db.execute(
            select(Asset).join(WatchlistItem, WatchlistItem.asset_id == Asset.id)
            .where(Asset.enabled.is_(True), WatchlistItem.news_enabled.is_(True))
            .distinct().order_by(Asset.id)
        ).scalars().all()
        return [{"asset_id": asset.id, "symbol": asset.symbol, "name": asset.name,
                 "asset_type": asset.asset_type, "venue": asset.venue,
                 "segment": asset.segment, "provider": asset.provider,
                 "enabled": asset.enabled, "news_enabled": True} for asset in rows]

    @app.get("/api/internal/default-contract-watchlist")
    def default_contract_watchlist(db=Depends(get_db)):
        """Keep the legacy hourly Telegram digest tied to its original owner."""
        owner = db.scalar(select(User).where(User.username == "default"))
        if owner is None:
            return []
        rows = db.scalars(
            select(Asset).join(WatchlistItem, WatchlistItem.asset_id == Asset.id)
            .where(WatchlistItem.user_id == owner.id, Asset.enabled.is_(True))
            .order_by(Asset.id)
        ).all()
        return [{"asset_id": asset.id, "symbol": asset.symbol, "name": asset.name,
                 "asset_type": asset.asset_type, "venue": asset.venue,
                 "segment": asset.segment, "provider": asset.provider,
                 "enabled": asset.enabled} for asset in rows]
