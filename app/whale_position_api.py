"""Authenticated UI for automatic wallet discovery; no wallet input required."""
from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from hyperliquid_whales import SOURCE, decimal, milliseconds
from whale_models import (WhaleAddress, WhaleEventDecision, WhalePositionEvent,
                          WhalePushPolicy, WhaleRuntime, WhaleSubscription)
from whale_monitoring import market_monitoring
from whale_push_policy import DEFAULT_POLICY, clear_pending_for_sub, policy_for
from whale_sources import SUBSCRIPTION_PATTERN, account_scope, market_identity, runtime_id, venue_for


class WhaleSubscriptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    coin: str = Field(pattern=SUBSCRIPTION_PATTERN)
    enabled: bool = True
    min_position_usd: float = Field(default=1000000, ge=1000, le=1000000000000)
    cooldown_seconds: int = Field(default=300, ge=0, le=86400)
    min_change_usd: float = Field(default=5000, ge=0, le=1000000000000)
    min_change_pct: float = Field(default=.5, ge=0, le=1000)
    aggregation_seconds: int = Field(default=300, ge=0, le=3600)
    priority_events: bool = True


def install_whale_routes(app, get_db, get_user):
    @app.get("/api/whales")
    def whales(db=Depends(get_db)):
        user = get_user(db)
        now = milliseconds()
        sources, markets = [], []
        for venue, label in (("trade_xyz", SOURCE), ("lighter", "Lighter 主网")):
            runtime_row = db.get(WhaleRuntime, runtime_id(venue))
            runtime = dict(runtime_row.data) if runtime_row else {}
            runtime["online"] = 0 < runtime.get("heartbeat_ms", 0) <= now and now - runtime["heartbeat_ms"] < 90000
            scope = account_scope(WhaleAddress.address, venue)
            runtime["address_count"] = db.scalar(select(func.count()).select_from(WhaleAddress).where(scope))
            runtime["pending_checks"] = db.scalar(select(func.count()).select_from(WhaleAddress).where(scope, WhaleAddress.next_check_ms <= now))
            markets.extend({**m, **market_identity(m["coin"], [m])} for m in runtime.get("markets", []))
            sources.append({"id": venue, "label": label, "runtime": runtime})
        runtime = sources[0]["runtime"]  # Compatibility for older clients; this worker delivers BOTH sources.
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
        decisions = {row.event_key: row.outcome for row in db.scalars(select(WhaleEventDecision).where(
            WhaleEventDecision.user_id == user.id,
            WhaleEventDecision.event_key.in_([p["event_key"] for p in events]))).all()}
        events = [{**p, "push_outcome": decisions.get(p["event_key"], "unrecorded")} for p in events]
        positions = []
        addresses = db.scalars(select(WhaleAddress).order_by(WhaleAddress.checked_ms.desc()).limit(20000)).all()
        for row in addresses:
            for coin, p in row.positions.items():
                if coin in by_coin and decimal(p["notional_usd"]) >= decimal(by_coin[coin].min_position_usd) and decimal(p["qty"]) != 0:
                    stamp = p.get("snapshot_ms", row.snapshot_ms)
                    identity = market_identity(coin, markets)
                    if p.get("symbol"):
                        identity["symbol"] = p["symbol"]  # Retain a verified symbol after delisting/outage.
                    positions.append({**p, "address": row.address, "coin": coin,
                        "snapshot_ms": stamp, "stale": now - stamp > 180000,
                        **identity})
        positions.sort(key=lambda p: decimal(p["notional_usd"]), reverse=True)
        return {"markets": markets, "runtime": runtime, "sources": sources,
            "subscriptions": [{"id": s.id, "coin": s.coin, "enabled": s.enabled,
                "min_position_usd": s.min_position_usd, "cooldown_seconds": s.cooldown_seconds,
                **market_identity(s.coin, markets),
                **policy_for(db, s)} for s in subs],
            "monitoring": [{**m, **market_identity(m["coin"], markets)}
                           for m in market_monitoring(db, user.id, subs, addresses, now)],
            "events": events, "positions": positions[:50],
            "coverage": "仅覆盖 trade.xyz 和 Lighter 主网的已选市场，不含 Robinhood。自动从公开成交发现账户；未导入全量历史，静默老仓位和核验间的短暂开平仓可能遗漏。"}

    @app.put("/api/whales/subscriptions")
    def save_whale_subscription(payload: WhaleSubscriptionInput, db=Depends(get_db)):
        user = get_user(db)
        runtime = db.get(WhaleRuntime, runtime_id(venue_for(payload.coin)))
        verified = runtime.data.get("markets", []) if runtime else []
        sub = db.scalar(select(WhaleSubscription).where(WhaleSubscription.user_id == user.id,
                                                       WhaleSubscription.coin == payload.coin))
        # A source outage must never prevent pausing an existing subscription.
        pausing = sub is not None and not payload.enabled
        if not pausing and not any(m["coin"] == payload.coin for m in verified):
            raise HTTPException(status_code=422, detail="该市场尚未通过行情源核验，请等待巨鲸服务同步市场目录。")
        if not pausing and milliseconds() - runtime.data.get("catalog_ms", 0) > 86400000:
            raise HTTPException(status_code=503, detail="市场目录已过期，请检查巨鲸服务连接。")
        values = payload.model_dump(exclude=set(DEFAULT_POLICY))
        changed = False
        if sub is None:
            sub = WhaleSubscription(user_id=user.id, started_ms=milliseconds(), **values)
            db.add(sub)
            db.flush()
        else:
            changed = any(getattr(sub, key) != value for key, value in values.items())
            if payload.enabled and not sub.enabled:
                sub.started_ms = milliseconds()
            for key, value in values.items():
                setattr(sub, key, value)
            if changed:
                clear_pending_for_sub(db, sub.id)
        current_policy = policy_for(db, sub)
        updated_policy = {**current_policy, **{key: getattr(payload, key)
            for key in set(DEFAULT_POLICY) & payload.model_fields_set}}
        policy = db.get(WhalePushPolicy, sub.id)
        if policy is None:
            policy = WhalePushPolicy(subscription_id=sub.id, data=updated_policy, updated_ms=milliseconds())
            db.add(policy)
        elif updated_policy != current_policy or changed:
            clear_pending_for_sub(db, sub.id)
            policy.data = updated_policy
            policy.updated_ms = milliseconds()
        db.commit()
        return {"id": sub.id, "status": "saved"}

    @app.delete("/api/whales/subscriptions/{subscription_id}")
    def delete_whale_subscription(subscription_id: int, db=Depends(get_db)):
        user = get_user(db)
        row = db.get(WhaleSubscription, subscription_id)
        if row is None or row.user_id != user.id:
            raise HTTPException(status_code=404, detail="Subscription not found")
        clear_pending_for_sub(db, row.id, "inactive")
        policy = db.get(WhalePushPolicy, row.id)
        if policy:
            db.delete(policy)
        db.flush()
        db.delete(row)
        db.commit()
        return {"status": "deleted"}
