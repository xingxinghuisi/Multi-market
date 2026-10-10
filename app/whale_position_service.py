"""Account-scoped whale views and durable notification delivery."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from hyperliquid_whales import event_text, milliseconds
from models import Notification, User
from telegram_service import CHAT_ID, send_telegram_message
from whale_models import WhalePositionDelivery, WhalePositionEvent, WhaleSubscription


def deliver_event(db, event, sub, delivery=None):
    """One delivery claim per user/event; only explicitly failed sends may retry."""
    payload = event.payload
    if not sub.enabled or event.coin != sub.coin or event.qualifying_usd < sub.min_position_usd:
        return "inactive"
    user = db.get(User, sub.user_id)
    if user is None:
        return "inactive"
    if delivery is None:
        delivery = db.scalar(select(WhalePositionDelivery).where(
            WhalePositionDelivery.user_id == user.id, WhalePositionDelivery.event_key == event.event_key))
        if delivery is not None:
            return "duplicate"
        # Cooldown is per wallet/market/user, so another whale cannot suppress this one.
        recent = db.scalar(select(Notification.id).join(WhalePositionDelivery,
            WhalePositionDelivery.notification_id == Notification.id).join(WhalePositionEvent,
            WhalePositionDelivery.event_key == WhalePositionEvent.event_key).where(
                WhalePositionDelivery.user_id == user.id, WhalePositionEvent.address == event.address,
                WhalePositionEvent.coin == event.coin, Notification.status.in_(["pending", "sent", "in_app"]),
                Notification.created_at > datetime.now(timezone.utc) - timedelta(seconds=sub.cooldown_seconds)).limit(1))
        if recent is not None:
            return "cooldown"
        title, message = event_text(payload)
        notification = Notification(user_id=user.id, category="whale_position", title=title,
                                    message=message, channel="in_app", status="in_app")
        db.add(notification)
        db.flush()
        delivery = WhalePositionDelivery(user_id=user.id, event_key=event.event_key,
                                          notification_id=notification.id, attempts=1)
        db.add(delivery)
    else:
        notification = db.get(Notification, delivery.notification_id)
        if notification is None or notification.status != "failed" or delivery.attempts >= 3:
            return "inactive"
        delivery.attempts += 1
    target = user.telegram_chat_id or (CHAT_ID if user.username == "default" else None)
    notification.channel = "telegram" if target else "in_app"
    notification.status = "pending" if target else "in_app"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return "duplicate"
    if not target:
        return "in_app"
    sent = send_telegram_message(notification.message, chat_id=target)
    notification.status = "sent" if sent else "failed"
    notification.sent_at = datetime.now(timezone.utc) if sent else None
    delivery.next_retry_ms = milliseconds() + 60000
    db.commit()
    return notification.status


def deliver_pending(db):
    # Recover committed events if the worker stopped before creating delivery records.
    # Do not backfill old events for newly created subscriptions.
    events = db.scalars(select(WhalePositionEvent).where(
        WhalePositionEvent.dispatched_ms == 0).order_by(WhalePositionEvent.observed_ms).limit(20)).all()
    for event in events:
        if milliseconds() - event.observed_ms < 3600000:
            for sub in db.scalars(select(WhaleSubscription).where(WhaleSubscription.enabled.is_(True),
                    WhaleSubscription.coin == event.coin, WhaleSubscription.min_position_usd <= event.qualifying_usd)).all():
                if event.observed_ms >= sub.started_ms:
                    deliver_event(db, event, sub)
        event.dispatched_ms = milliseconds()
        db.commit()
    rows = db.scalars(select(WhalePositionDelivery).join(Notification,
        WhalePositionDelivery.notification_id == Notification.id).where(
            Notification.status == "failed", WhalePositionDelivery.attempts < 3,
            WhalePositionDelivery.next_retry_ms <= milliseconds()).limit(20)).all()
    for delivery in rows:
        event = db.get(WhalePositionEvent, delivery.event_key)
        sub = db.scalar(select(WhaleSubscription).where(WhaleSubscription.user_id == delivery.user_id,
                                                      WhaleSubscription.coin == event.coin))
        if (sub is not None and sub.enabled and sub.min_position_usd <= event.qualifying_usd
                and event.observed_ms >= sub.started_ms and milliseconds() - event.observed_ms < 3600000):
            deliver_event(db, event, sub, delivery=delivery)
        else:
            # Removed/paused/obsolete subscriptions must not occupy the retry queue forever.
            notification = db.get(Notification, delivery.notification_id)
            notification.status = "cancelled"
            db.commit()
