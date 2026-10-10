"""Account-owned subscriptions, additive upgrades and durable delivery records."""
from datetime import datetime, timedelta, timezone
import re
import threading

from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import Base
from models import AlertSubscription, Asset, Notification, SubscriptionDelivery, User, WatchlistItem
from schemas import WhaleConfig
from telegram_service import CHAT_ID, send_telegram_message

# One API process is used in Compose. Serialize cooldown checks and event claims.
_delivery_lock = threading.Lock()


def supports_subscription(asset):
    return bool(asset and asset.asset_type == "crypto" and asset.venue == "BINANCE"
                and asset.currency == "USDT"
                and (re.search(r"FUTURE|PERPETUAL", asset.segment or "", re.I)
                     or (asset.segment or "").upper() in {"USD_M", "USD-M", "CONTRACT", "SWAP"})
                and re.fullmatch(r"[A-Z0-9]{2,50}", asset.symbol))


def subscription_config(subscription):
    if subscription.alert_type == "whale_print":
        return WhaleConfig.model_validate(subscription.config or {}).model_dump()
    return {}


def initialize_subscription_tables(engine):
    """Add tables only. Preserve legacy owner's digest selection on the first upgrade."""
    first_upgrade = not inspect(engine).has_table("alert_subscriptions")
    Base.metadata.create_all(engine, tables=[AlertSubscription.__table__, SubscriptionDelivery.__table__],
                             checkfirst=True)
    if not first_upgrade or not inspect(engine).has_table("watchlist_items"):
        return
    with Session(engine) as db:
        owner = db.scalar(select(User).where(User.username == "default"))
        if owner is None:
            return
        assets = db.scalars(select(Asset).join(WatchlistItem, WatchlistItem.asset_id == Asset.id)
                            .where(WatchlistItem.user_id == owner.id, Asset.enabled.is_(True))).all()
        for asset in assets:
            if supports_subscription(asset):
                db.add(AlertSubscription(user_id=owner.id, asset_id=asset.id,
                                         alert_type="longshort_digest", enabled=True, config={}))
        db.commit()


def deliver_subscription_event(db, subscription_id, payload):
    # Commit the pending record before contacting Telegram so a retried HTTP request cannot resend it.
    with _delivery_lock:
        sub = db.get(AlertSubscription, subscription_id)
        if sub is None or not sub.enabled or not supports_subscription(db.get(Asset, sub.asset_id)):
            return {"status": "inactive"}
        user = db.get(User, sub.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        prior = db.scalar(select(SubscriptionDelivery).where(
            SubscriptionDelivery.subscription_id == sub.id,
            SubscriptionDelivery.event_key == payload.event_key))
        notification = db.get(Notification, prior.notification_id) if prior else None
        if notification is not None and notification.status != "failed":
            return {"status": notification.status, "duplicate": True, "notification_id": notification.id}
        if sub.alert_type == "whale_print":
            try:
                config = subscription_config(sub)
            except ValueError:
                return {"status": "invalid_config"}
            if payload.notional_usd is None:
                raise HTTPException(status_code=422, detail="Whale event requires notional_usd")
            if payload.notional_usd < config["whale_min_usd"]:
                return {"status": "below_threshold"}
            cooldown = config["cooldown_seconds"]
            recent = db.scalar(select(Notification.id).join(
                SubscriptionDelivery, SubscriptionDelivery.notification_id == Notification.id).where(
                    SubscriptionDelivery.subscription_id == sub.id,
                    Notification.status.in_(["pending", "sent", "in_app"]),
                    Notification.created_at > datetime.now(timezone.utc) - timedelta(seconds=cooldown)).limit(1))
            if recent is not None:
                return {"status": "cooldown"}
        # Only the legacy workspace may use the deployment's default chat target.
        target = user.telegram_chat_id or (CHAT_ID if user.username == "default" else None)
        if notification is None:
            notification = Notification(user_id=user.id, asset_id=sub.asset_id,
                category=sub.alert_type, title=payload.title, message=payload.message,
                channel="telegram" if target else "in_app", status="pending" if target else "in_app")
            db.add(notification)
            db.flush()
            db.add(SubscriptionDelivery(subscription_id=sub.id, event_key=payload.event_key,
                                        notification_id=notification.id))
        else:
            notification.status = "pending" if target else "in_app"
            notification.channel = "telegram" if target else "in_app"
            notification.created_at = datetime.now(timezone.utc)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return {"status": "duplicate", "duplicate": True}
        notification_id = notification.id
        if not target:
            return {"status": "in_app", "notification_id": notification_id}

    sent = send_telegram_message(notification.message, chat_id=target)
    notification.status = "sent" if sent else "failed"
    notification.sent_at = datetime.now(timezone.utc) if sent else None
    db.commit()
    return {"status": notification.status, "notification_id": notification_id}
