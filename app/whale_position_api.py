"""Authenticated UI for automatic wallet discovery; no wallet input required."""
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from hyperliquid_whales import MARKET_PATTERN, SOURCE, decimal, milliseconds
from whale_models import WhaleAddress, WhalePositionEvent, WhaleRuntime, WhaleSubscription


class WhaleSubscriptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    coin: str = Field(pattern=MARKET_PATTERN)
    enabled: bool = True
    min_position_usd: float = Field(default=1000000, ge=1000, le=1000000000000)
    cooldown_seconds: int = Field(default=300, ge=0, le=86400)


def install_whale_routes(app, get_db, get_user):
    @app.get("/api/whales")
    def whales(db=Depends(get_db)):
        user = get_user(db)
        runtime_row = db.get(WhaleRuntime, 1)
        runtime = dict(runtime_row.data) if runtime_row else {}
        now = milliseconds()
        runtime["online"] = now - runtime.get("heartbeat_ms", 0) < 90000
        runtime["address_count"] = db.scalar(select(func.count()).select_from(WhaleAddress))
        runtime["pending_checks"] = db.scalar(select(func.count()).select_from(WhaleAddress).where(WhaleAddress.next_check_ms <= now))
        subs = db.scalars(select(WhaleSubscription).where(WhaleSubscription.user_id == user.id).order_by(WhaleSubscription.id)).all()
        by_coin = {s.coin: s for s in subs if s.enabled}
        events = []
        if by_coin:
            # Filter before limiting so busy low-value markets cannot hide another subscription.
            from sqlalchemy import and_, or_
            conditions = [and_(WhalePositionEvent.coin == coin,
                WhalePositionEvent.qualifying_usd >= s.min_position_usd,
                WhalePositionEvent.observed_ms >= s.started_ms) for coin, s in by_coin.items()]
            events = [r.payload for r in db.scalars(select(WhalePositionEvent).where(or_(*conditions))
                       .order_by(WhalePositionEvent.observed_ms.desc()).limit(50)).all()]
        positions = []
        for row in db.scalars(select(WhaleAddress).order_by(WhaleAddress.checked_ms.desc()).limit(10000)).all():
            for coin, p in row.positions.items():
                if coin in by_coin and decimal(p["notional_usd"]) >= decimal(by_coin[coin].min_position_usd) and decimal(p["qty"]) != 0:
                    stamp = p.get("snapshot_ms", row.snapshot_ms)
                    positions.append({**p, "address": row.address, "coin": coin,
                        "snapshot_ms": stamp, "stale": now - stamp > 180000,
                        "source": SOURCE})
        positions.sort(key=lambda p: decimal(p["notional_usd"]), reverse=True)
        return {"markets": runtime.get("markets", []), "runtime": runtime,
            "subscriptions": [{"id": s.id, "coin": s.coin, "enabled": s.enabled,
                "min_position_usd": s.min_position_usd, "cooldown_seconds": s.cooldown_seconds} for s in subs],
            "events": events, "positions": positions[:50],
            "coverage": "仅覆盖 Hyperliquid / trade.xyz 已选市场。自动从公开成交发现地址；未导入全量历史，静默老仓位和核验间的短暂开平仓可能遗漏。"}

    @app.put("/api/whales/subscriptions")
    def save_whale_subscription(payload: WhaleSubscriptionInput, db=Depends(get_db)):
        user = get_user(db)
        runtime = db.get(WhaleRuntime, 1)
        verified = runtime.data.get("markets", []) if runtime else []
        sub = db.scalar(select(WhaleSubscription).where(WhaleSubscription.user_id == user.id,
                                                       WhaleSubscription.coin == payload.coin))
        # A source outage must never prevent pausing an existing subscription.
        pausing = sub is not None and not payload.enabled
        if not pausing and not any(m["coin"] == payload.coin for m in verified):
            raise HTTPException(status_code=422, detail="该市场尚未通过行情源核验，请等待巨鲸服务同步市场目录。")
        if not pausing and milliseconds() - runtime.data.get("catalog_ms", 0) > 86400000:
            raise HTTPException(status_code=503, detail="市场目录已过期，请检查巨鲸服务连接。")
        if sub is None:
            sub = WhaleSubscription(user_id=user.id, started_ms=milliseconds(), **payload.model_dump())
            db.add(sub)
        else:
            if payload.enabled and not sub.enabled:
                sub.started_ms = milliseconds()
            for key, value in payload.model_dump().items():
                setattr(sub, key, value)
        db.commit()
        return {"id": sub.id, "status": "saved"}

    @app.delete("/api/whales/subscriptions/{subscription_id}")
    def delete_whale_subscription(subscription_id: int, db=Depends(get_db)):
        user = get_user(db)
        row = db.get(WhaleSubscription, subscription_id)
        if row is None or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Subscription not found")
        db.delete(row)
        db.commit()
        return {"status": "deleted"}
