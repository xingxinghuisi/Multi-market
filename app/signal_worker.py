"""One shared worker: closed-candle technical signals, Gemini, and cost warnings."""
import argparse
import base64
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import requests
from sqlalchemy import select

from database import SessionLocal, engine
from gemini_service import (analyze, billing_month, cloud_session, configuration,
                            notify_budget, usage_summary)
from models import AlertSubscription, Asset, Notification, SubscriptionDelivery
from schemas import SubscriptionEvent
from signal_models import TechnicalState, initialize_signal_tables
from subscription_service import deliver_subscription_event, supports_subscription
from technical_indicators import TechnicalConfig, closed_candles, evaluate


def fetch_candles(symbol, timeframe):
    proxy = os.getenv("BINANCE_PROXY_URL", "").strip()
    response = requests.get("https://fapi.binance.com/fapi/v1/klines",
        params={"symbol": symbol, "interval": timeframe, "limit": 400}, timeout=(5, 15),
        proxies={"http": proxy, "https": proxy} if proxy else None)
    response.raise_for_status()
    return response.json()


def configuration_key(config):
    return hashlib.sha256(json.dumps(config.model_dump(), sort_keys=True).encode()).hexdigest()


def cooling_down(db, sub, config, now):
    if config.cooldown_seconds == 0:
        return False
    return db.scalar(select(Notification.id).join(
        SubscriptionDelivery, SubscriptionDelivery.notification_id == Notification.id).where(
            SubscriptionDelivery.subscription_id == sub.id,
            Notification.status.in_(["pending", "sent", "in_app"]),
            Notification.created_at > now - timedelta(seconds=config.cooldown_seconds)).limit(1)) is not None


def format_message(symbol, snapshot, result, note=None):
    title = f"📊 {symbol} · {snapshot['timeframe']} 技术信号 · ${snapshot['close']:.8g}"
    lines = [title, *[f"• {signal}" for signal in snapshot["signals"]]]
    if result:
        bias = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}[result["bias"]]
        lines += [f"Gemini 解读：{bias}｜{result['summary']}",
                  *[f"依据：{reason}" for reason in result["reasons"]],
                  *[f"注意：{risk}" for risk in result["risks"]]]
    elif note:
        lines.append(note)
    stamp = datetime.fromtimestamp((snapshot["candle_close_ms"] + 1) / 1000, timezone.utc)
    lines.append(f"Binance 合约 · {stamp.astimezone(timezone(timedelta(hours=8))):%m/%d %H:%M} 北京时间收盘")
    return title, "\n".join(lines)


def process_subscription(db, sub, asset, candles, now, generator=None, context=None):
    config = TechnicalConfig.model_validate(sub.config or {})
    snapshot = evaluate(candles, config)
    snapshot["symbol"] = asset.symbol
    if context is not None:
        snapshot["higher_timeframe"] = context
    state = db.get(TechnicalState, sub.id)
    config_key = configuration_key(config)
    subscription_id = sub.id
    same_candle = state and state.config_key == config_key and state.candle_close_ms == snapshot["candle_close_ms"]
    if same_candle:
        snapshot = state.snapshot
        if snapshot.get("message"):
            db.expire_all()
            return deliver_subscription_event(db, sub.id, SubscriptionEvent(
                event_key=snapshot["event_key"], title=snapshot["title"], message=snapshot["message"]))
        if snapshot.get("baseline") or snapshot.get("skip_reason") or not snapshot["signals"]:
            return {"status": "checked"}
    else:
        baseline = state is None or state.config_key != config_key
        snapshot["baseline"] = baseline
        if state is None:
            state = TechnicalState(subscription_id=sub.id, config_key=config_key,
                                   candle_close_ms=snapshot["candle_close_ms"], snapshot=snapshot)
            db.add(state)
        else:
            state.config_key, state.candle_close_ms, state.snapshot = config_key, snapshot["candle_close_ms"], snapshot
        state.updated_at = now
        db.commit()
        if baseline:
            return {"status": "baseline"}
    if not snapshot["signals"]:
        return {"status": "no_signal"}
    if cooling_down(db, sub, config, now):
        state.snapshot = {**snapshot, "skip_reason": "cooldown"}
        db.commit()
        return {"status": "cooldown"}
    result, note = (analyze(db, {k: v for k, v in snapshot.items() if k != "baseline"},
                            generator=generator, now=now) if config.ai_enabled else (None, "AI 解读已关闭"))
    title, message = format_message(asset.symbol, snapshot, result, note)
    event_key = f"technical:{snapshot['timeframe']}:{snapshot['candle_close_ms']}:{config_key[:12]}"
    state.snapshot = {**snapshot, "analysis": result, "ai_note": note, "title": title,
                      "message": message, "event_key": event_key}
    db.commit()
    db.expire_all()
    current = db.get(AlertSubscription, subscription_id)
    if current is None or not current.enabled or configuration_key(TechnicalConfig.model_validate(current.config or {})) != config_key:
        return {"status": "subscription_changed"}
    return deliver_subscription_event(db, subscription_id, SubscriptionEvent(event_key=event_key, title=title, message=message))


def handle_billing_message(db, message, expected_budget_id, sender=None, now=None):
    """Validate an actual Cloud Budget report, not a forecast or arbitrary Pub/Sub message."""
    now = now or datetime.now(timezone.utc)
    if message.get("attributes", {}).get("budgetId") != expected_budget_id:
        return True
    data = json.loads(base64.b64decode(message["data"], validate=True))
    if data.get("currencyCode") != "USD":
        raise ValueError("Cloud budget must use USD")
    start = datetime.fromisoformat(data["costIntervalStart"].replace("Z", "+00:00"))
    if start.tzinfo is None:
        raise ValueError("Invalid billing period")
    month = billing_month(start)
    if month != billing_month(now):
        return True
    cost = Decimal(str(data["costAmount"]))
    if not cost.is_finite() or cost < 0:
        raise ValueError("Invalid billing cost")
    from gemini_service import budget_threshold
    return cost < budget_threshold() or notify_budget(db, cost, source="cloud_billing", month=month, sender=sender)


def poll_cloud_billing(db, session=None, now=None):
    subscription = os.getenv("GEMINI_BILLING_SUBSCRIPTION", "")
    budget_id = os.getenv("GEMINI_BILLING_BUDGET_ID", "")
    if not subscription or not budget_id:
        return
    if not re.fullmatch(r"projects/[a-z0-9-]+/subscriptions/[A-Za-z0-9_.~-]+", subscription):
        raise ValueError("Invalid billing subscription resource")
    owned = session is None
    session = session or cloud_session()
    base = f"https://pubsub.googleapis.com/v1/{subscription}"
    try:
        response = session.post(f"{base}:pull", json={"maxMessages": 10}, timeout=(5, 15))
        response.raise_for_status()
        ack = []
        for received in response.json().get("receivedMessages", []):
            try:
                done = handle_billing_message(db, received["message"], budget_id, now=now)
                if done:
                    ack.append(received["ackId"])
            except (KeyError, ValueError, TypeError):
                print("[AI BILLING] invalid budget message; check USD/monthly budget settings", flush=True)
        if ack:
            response = session.post(f"{base}:acknowledge", json={"ackIds": ack}, timeout=(5, 10))
            response.raise_for_status()
    finally:
        if owned:
            session.close()


def run_once(sessions=SessionLocal, reader=fetch_candles, generator=None, now=None):
    now = now or datetime.now(timezone.utc)
    cache = {}
    with sessions() as db:
        rows = db.execute(select(AlertSubscription, Asset).join(Asset).where(
            AlertSubscription.alert_type == "technical_signal", AlertSubscription.enabled.is_(True),
            Asset.enabled.is_(True))).all()
        for sub, asset in rows:
            subscription_id = sub.id
            if not supports_subscription(asset):
                continue
            try:
                config = TechnicalConfig.model_validate(sub.config or {})
                key = (asset.symbol, config.timeframe)
                if key not in cache:
                    cache[key] = closed_candles(reader(*key), config.timeframe, int(now.timestamp() * 1000))
                candles = cache[key]
                context = None
                if evaluate(candles, config)["signals"]:
                    higher = {"15m": "1h", "1h": "4h", "4h": "1d"}.get(config.timeframe)
                    if higher:
                        try:
                            context_key = (asset.symbol, higher, candles[-1]["end"] + 1)
                            if context_key not in cache:
                                cache[context_key] = closed_candles(reader(asset.symbol, higher), higher, candles[-1]["end"] + 1)
                            higher_config = config.model_copy(update={"timeframe": higher, "indicators": []})
                            h = evaluate(cache[context_key], higher_config)
                            context = {k: h[k] for k in ("timeframe", "candle_time", "close", "indicators")}
                        except Exception:
                            context = {"timeframe": higher, "unavailable": True}
                result = process_subscription(db, sub, asset, candles, now, generator, context)
                if result["status"] not in {"checked", "no_signal", "sent", "in_app"}:
                    print(f"[SIGNALS] {asset.symbol} subscription={sub.id} status={result['status']}", flush=True)
            except Exception as error:
                db.rollback()
                print(f"[SIGNALS] subscription={subscription_id} error={type(error).__name__}", flush=True)
        summary = usage_summary(db, now)
        notify_budget(db, summary["estimated_usd"], month=summary["month"])
        try:
            poll_cloud_billing(db, now=now)
        except Exception as error:
            db.rollback()
            print(f"[AI BILLING] poll failed: {type(error).__name__}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    initialize_signal_tables(engine)
    print(f"[SIGNALS] worker started; Gemini configured={configuration()['configured']}; monthly warning=$8.50 by default", flush=True)
    while True:
        try:
            run_once()
        except Exception as error:
            print(f"[SIGNALS] cycle failed: {type(error).__name__}", flush=True)
        if args.once:
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
