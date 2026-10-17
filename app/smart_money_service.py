"""Compare sampled groups, never infer individual trades or actual event times."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
import threading

from fastapi import Depends, HTTPException
from sqlalchemy import select

from binance_smart_money import client, number, SmartMoneyUnavailable
from models import AlertSubscription, Asset
from schemas import SubscriptionEvent
from smart_money_models import SmartMoneyState
from smart_money_pnl import attach_valuation, pnl_comparison
from subscription_service import deliver_subscription_event, subscription_config, supports_subscription

MAX_COMPARISON_GAP = 1800
MAX_READ_AGE = 900
smart_money_lock = threading.RLock()  # Polling and personal setting changes share one API process.
UTC8 = timezone(timedelta(hours=8))


def config_key(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def observed(snapshot):
    stamp = datetime.fromisoformat(snapshot["fetched_at"])
    if stamp.tzinfo is None:
        raise ValueError("An observation needs an explicit timezone")
    return stamp


def changes(before, after, config):
    """OR across selected metrics/sides; percentages require a positive denominator."""
    result = []
    for side in ("long", "short"):
        old, new = before.get("sides", {}).get(side, {}), after.get("sides", {}).get(side, {})
        for field, selected, threshold in (
            ("whales", config["watch_whale_count"], config["min_whale_count_change"]),
            ("whale_quantity", config["watch_whale_quantity"], config["min_whale_quantity_change_pct"]),
        ):
            previous, current = number(old.get(field), integer=field == "whales"), number(new.get(field), integer=field == "whales")
            if not selected or previous is None or current is None:
                continue
            delta = current - previous
            if delta == 0:
                continue
            pct = delta / previous * 100 if previous > 0 else None
            if pct is not None and not math.isfinite(pct):
                pct = None
            magnitude = abs(delta) if field == "whales" else (abs(pct) if pct is not None else None)
            if magnitude is not None and magnitude >= threshold:
                result.append({"side": side, "field": field, "before": previous,
                               "after": current, "delta": delta, "pct": pct})
    return result


def format_number(value):
    return f"{value:,.8f}".rstrip("0").rstrip(".")


def build_message(symbol, before, after, differences):
    title = f"🐋 {symbol} 聪明钱群体变化"
    lines = [title]
    for change in differences:
        side = "多头" if change["side"] == "long" else "空头"
        if change["field"] == "whales":
            lines.append(f"{side}巨鲸：{int(change['before'])} → {int(change['after'])}（{int(change['delta']):+d} 人）")
        else:
            lines.append(f"{side}巨鲸持仓数量：{format_number(change['before'])} → "
                         f"{format_number(change['after'])}（{change['pct']:+.2f}%）")
    pnl = after.get("pnl") or {}
    for side, label in (("long", "多头"), ("short", "空头")):
        avg = after.get("sides", {}).get(side, {}).get("whale_avg_entry_price")
        value = pnl.get("sides", {}).get(side, {}).get("whales_usdt")
        entry = f"${format_number(avg)}" if avg is not None else "未提供"
        lines.append(f"{label}巨鲸开仓均价：{entry}｜浮盈亏：{signed_money(value)}")
    comparison = after.get("pnl_comparison") or {}
    if comparison:
        long_delta = comparison["sides"]["long"]["whales_usdt"]
        short_delta = comparison["sides"]["short"]["whales_usdt"]
        lines.append(f"较上次采样：多头 {signed_money(long_delta)}｜空头 {signed_money(short_delta)}")
    if pnl.get("price") is not None:
        quote_time = datetime.fromisoformat(pnl["quote_at"]).astimezone(UTC8).strftime("%m/%d %H:%M:%S")
        lines.append(f"参考成交价：${format_number(pnl['price'])}（{quote_time} 北京时间）")
    else:
        lines.append("浮盈亏暂不可算：行情或持仓字段不足/过旧")
    start, end = (observed(item).astimezone(UTC8).strftime("%m/%d %H:%M") for item in (before, after))
    lines.extend([f"观察：{start} → {end} 北京时间",
                  "浮盈亏为快照计算值，含价格/样本变化，不含费用；非已实现收益、不是个人成交。源时间含义待核实。"])
    return title, "\n".join(lines)


def signed_money(value):
    if value is None:
        return "未提供"
    return f"{'-' if value < 0 else '+' if value > 0 else ''}${abs(value):,.2f}"


def process_snapshot(db, sub, asset, snapshot, now=None):
    now = now or datetime.now(timezone.utc)
    config = subscription_config(sub)
    key = config_key(config)
    state = db.get(SmartMoneyState, sub.id)
    if state is None:
        state = SmartMoneyState(subscription_id=sub.id, config_key=key)
        db.add(state)
    state.checked_at = now
    before = state.snapshot if state.config_key == key else None
    state.config_key = key
    if snapshot.get("refresh_error"):
        state.status = "source_error"
        db.commit()
        return {"status": state.status}
    try:
        stamp = observed(snapshot)
        age = (now - stamp).total_seconds()
        if (snapshot.get("market") != f"binance:usdm:{asset.symbol}"
                or snapshot.get("scope") != "aggregate"
                or not re.fullmatch(r"[0-9a-f]{64}", snapshot.get("fingerprint", ""))
                or age < -60 or age > MAX_READ_AGE):
            raise ValueError("Invalid or old observation")
    except (KeyError, TypeError, ValueError, OverflowError):
        state.status = "invalid_observation"
        db.commit()
        return {"status": state.status}
    if before is not None and stamp <= observed(before):
        # Reading a shared cached observation is not a new measurement.
        db.commit()
        return {"status": "cached"}
    differences = []
    gap = (stamp - observed(before)).total_seconds() if before is not None else None
    if before is None or gap > MAX_COMPARISON_GAP:
        state.status = "baseline" if before is None else "gap_reset"
    else:
        differences = changes(before, snapshot, config)
        state.status = "below_threshold" if not differences else "ready"
    # Persist the new comparison checkpoint before delivery, including filtered/cooldown intervals.
    # A restart never reconstructs earlier movements as fresh notifications.
    snapshot = attach_valuation(db, asset, snapshot, now)
    snapshot["pnl_comparison"] = pnl_comparison(before, snapshot)
    state.snapshot = snapshot
    db.commit()
    if not differences:
        return {"status": state.status}
    title, message = build_message(asset.symbol, before, snapshot, differences)
    result = deliver_subscription_event(db, sub.id, SubscriptionEvent(
        event_key=f"smart:{sub.id}:{int(stamp.timestamp()*1000)}", title=title, message=message),
        verified_smart_money=True)
    db.expire_all()
    state = db.get(SmartMoneyState, sub.id)
    if state is not None:
        state.status = result["status"]
    db.commit()
    return result


def monitoring_status(db, subscription):
    if not subscription.enabled:
        return {"status": "paused", "checked_at": None, "observed_at": None}
    state = db.get(SmartMoneyState, subscription.id)
    return {"status": state.status if state else "waiting",
            "checked_at": state.checked_at if state else None,
            "observed_at": (state.snapshot or {}).get("fetched_at") if state else None,
            "pnl_comparison": (state.snapshot or {}).get("pnl_comparison") if state else None}


def install_smart_money_routes(app, get_db):
    @app.post("/api/internal/smart-money/{asset_id}/poll")
    def poll(asset_id: int, db=Depends(get_db)):
        asset = db.get(Asset, asset_id)
        if not supports_subscription(asset) or not asset.enabled:
            raise HTTPException(status_code=404, detail="Unsupported or disabled asset")

        def subscriptions():
            return db.scalars(select(AlertSubscription.id).where(
                AlertSubscription.asset_id == asset_id, AlertSubscription.alert_type == "smart_money",
                AlertSubscription.enabled.is_(True)).order_by(AlertSubscription.id)).all()

        if not subscriptions():
            return {"status": "inactive", "results": []}
        try:
            # Settings remain editable during upstream network waits.
            snapshot = client.get(asset.symbol)
        except SmartMoneyUnavailable as error:
            snapshot = {"refresh_error": str(error), "retry_after_seconds": error.retry_after}
        db.expire_all()
        results = []
        for ident in subscriptions():
            # Serialize each account's comparison/delivery with its settings, not the entire batch.
            with smart_money_lock:
                db.expire_all()
                asset = db.get(Asset, asset_id)
                sub = db.get(AlertSubscription, ident)
                if asset is None or not asset.enabled or sub is None or not sub.enabled:
                    continue
                try:
                    result = process_snapshot(db, sub, asset, snapshot)
                except ValueError:
                    result = {"status": "invalid_config"}
                results.append({"subscription_id": sub.id, **result})
        return {"status": "source_error" if snapshot.get("refresh_error") else "checked",
                "retry_after_seconds": snapshot.get("retry_after_seconds"), "results": results}
