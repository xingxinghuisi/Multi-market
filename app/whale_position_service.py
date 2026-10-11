"""Account-scoped whale views and durable notification delivery."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from hyperliquid_whales import decimal, event_text, milliseconds
from models import Notification, User
from telegram_service import CHAT_ID, send_telegram_message
from whale_models import (WhaleAddress, WhaleAdjustmentBatch, WhaleEventDecision, WhalePositionDelivery,
                          WhalePositionEvent, WhalePushPolicy, WhaleSubscription)
from whale_push_policy import (ADJUSTMENTS, PRIORITY, adjustment_passes, can_merge,
                               discard_batch, merged_payload, policy_for)


def deliver_event(db, event, sub, delivery=None, payload_override=None, ignore_cooldown=False):
    """One delivery claim per user/event; only explicitly failed sends may retry."""
    payload = payload_override or event.payload
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
                Notification.created_at > datetime.fromtimestamp(milliseconds() / 1000, timezone.utc)
                    - timedelta(seconds=sub.cooldown_seconds)).limit(1))
        if recent is not None and not ignore_cooldown:
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


def record_decision(db, event, sub, outcome):
    if outcome == "duplicate":
        delivery = db.scalar(select(WhalePositionDelivery).where(
            WhalePositionDelivery.user_id == sub.user_id, WhalePositionDelivery.event_key == event.event_key))
        notice = db.get(Notification, delivery.notification_id) if delivery else None
        outcome = notice.status if notice else outcome
    row = db.get(WhaleEventDecision, (sub.user_id, event.event_key))
    if row is None:
        row = WhaleEventDecision(user_id=sub.user_id, event_key=event.event_key, coin=event.coin,
                                 observed_ms=event.observed_ms, outcome=outcome)
        db.add(row)
    else:
        row.outcome = outcome
    return outcome


def finish_batch(db, batch, sub, outcome):
    keys = batch.data["event_keys"]
    if outcome == "duplicate":
        delivery = db.scalar(select(WhalePositionDelivery).where(
            WhalePositionDelivery.user_id == sub.user_id, WhalePositionDelivery.event_key == keys[-1]))
        notice = db.get(Notification, delivery.notification_id) if delivery else None
        outcome = notice.status if notice else "duplicate"
    for key in keys:
        row = db.get(WhaleEventDecision, (sub.user_id, key))
        if row:
            row.outcome = ("merged" if key != keys[-1] and outcome in {"sent", "in_app", "failed", "pending"}
                           else outcome)
    db.delete(batch)


def flush_batch(db, batch, sub, now):
    data = batch.data
    event = db.get(WhalePositionEvent, data["event_keys"][-1])
    if (sub is None or not sub.enabled or event is None or event.observed_ms < sub.started_ms
            or now - event.observed_ms >= 3600000):
        discard_batch(db, batch, "inactive")
        return
    wallet = db.get(WhaleAddress, batch.address)
    current = wallet.positions.get(event.coin) if wallet else None
    if (current and current.get("snapshot_ms", wallet.snapshot_ms) > data["payload"]["snapshot_ms"]
            and decimal(current["qty"]) != decimal(data["payload"]["qty"])):
        # A later subthreshold close may not create a public event at all.
        # Never send an older buffered position after verification superseded it.
        discard_batch(db, batch, "superseded")
        return
    policy = policy_for(db, sub)
    if event.qualifying_usd < sub.min_position_usd:
        discard_batch(db, batch, "below_position")
        return
    if adjustment_passes(data["payload"], policy):
        result = deliver_event(db, event, sub, payload_override=data["payload"])
        if result != "cooldown" or now >= batch.expires_ms:
            finish_batch(db, batch, sub, result)
    elif now >= batch.expires_ms:
        discard_batch(db, batch, "below_change")


def process_event(db, event, sub):
    """Record a personal outcome once; aggregation is persisted across restarts."""
    existing = db.get(WhaleEventDecision, (sub.user_id, event.event_key))
    if existing:
        return existing.outcome
    if not sub.enabled or event.observed_ms < sub.started_ms:
        result = record_decision(db, event, sub, "inactive")
        db.commit()
        return result
    batch = db.get(WhaleAdjustmentBatch, (sub.id, event.address))
    if event.qualifying_usd < sub.min_position_usd:
        if batch:
            discard_batch(db, batch, "below_position")
        result = record_decision(db, event, sub, "below_position")
        db.commit()
        return result
    payload, policy = event.payload, policy_for(db, sub)
    if payload["kind"] not in ADJUSTMENTS:
        if batch:
            discard_batch(db, batch, "superseded")
        result = deliver_event(db, event, sub,
            ignore_cooldown=policy["priority_events"] and payload["kind"] in PRIORITY)
        record_decision(db, event, sub, result)
        db.commit()
        return result

    if batch and event.observed_ms >= batch.expires_ms:
        flush_batch(db, batch, sub, event.observed_ms)
        db.flush()
        batch = None
    if batch and not can_merge(batch.data["payload"], payload):
        discard_batch(db, batch, "superseded")
        db.flush()
        batch = None
    merged = merged_payload(batch.data["payload"], payload) if batch else payload
    keys = [*batch.data["event_keys"], event.event_key] if batch else [event.event_key]
    ready = adjustment_passes(merged, policy)
    result = deliver_event(db, event, sub, payload_override=merged) if ready else "below_change"
    if result not in {"below_change", "cooldown"}:
        record_decision(db, event, sub, result)
        db.flush()
        if batch:
            batch.data = {**batch.data, "payload": merged, "event_keys": keys}
            finish_batch(db, batch, sub, result)
        db.commit()
        return result
    if not policy["aggregation_seconds"]:
        if batch:
            discard_batch(db, batch, "settings_changed")
        record_decision(db, event, sub, result)
        db.commit()
        return result
    data = {"payload": merged, "event_keys": keys, "user_id": sub.user_id}
    if batch:
        batch.data = data
    else:
        db.add(WhaleAdjustmentBatch(subscription_id=sub.id, address=event.address, data=data,
            expires_ms=event.observed_ms + policy["aggregation_seconds"] * 1000))
    record_decision(db, event, sub, "buffering")
    db.commit()
    return "buffering"


def flush_batches(db):
    now = milliseconds()
    for batch in db.scalars(select(WhaleAdjustmentBatch).order_by(WhaleAdjustmentBatch.expires_ms).limit(200)).all():
        payload = batch.data["payload"]
        last_event = db.get(WhalePositionEvent, batch.data["event_keys"][-1])
        # Process later committed changes before sending an older buffered state.
        pending = db.scalar(select(WhalePositionEvent.event_key).where(
            WhalePositionEvent.dispatched_ms == 0, WhalePositionEvent.address == batch.address,
            WhalePositionEvent.coin == payload["coin"],
            WhalePositionEvent.observed_ms > last_event.observed_ms).limit(1)) if last_event else None
        if pending:
            continue
        flush_batch(db, batch, db.get(WhaleSubscription, batch.subscription_id), now)
        db.commit()


def deliver_pending(db):
    # Recover committed events if the worker stopped before creating delivery records.
    # Do not backfill old events for newly created subscriptions.
    events = db.scalars(select(WhalePositionEvent).where(
        WhalePositionEvent.dispatched_ms == 0).order_by(WhalePositionEvent.observed_ms).limit(20)).all()
    for event in events:
        if milliseconds() - event.observed_ms < 3600000:
            for sub in db.scalars(select(WhaleSubscription).where(WhaleSubscription.enabled.is_(True),
                    WhaleSubscription.coin == event.coin)).all():
                if event.observed_ms >= sub.started_ms:
                    process_event(db, event, sub)
        event.dispatched_ms = milliseconds()
        db.commit()
    flush_batches(db)
    rows = db.scalars(select(WhalePositionDelivery).join(Notification,
        WhalePositionDelivery.notification_id == Notification.id).where(
            Notification.status == "failed", WhalePositionDelivery.attempts < 3,
            WhalePositionDelivery.next_retry_ms <= milliseconds()).limit(20)).all()
    for delivery in rows:
        event = db.get(WhalePositionEvent, delivery.event_key)
        sub = db.scalar(select(WhaleSubscription).where(WhaleSubscription.user_id == delivery.user_id,
                                                      WhaleSubscription.coin == event.coin))
        policy = db.get(WhalePushPolicy, sub.id) if sub else None
        if (sub is not None and sub.enabled and sub.min_position_usd <= event.qualifying_usd
                and event.observed_ms >= sub.started_ms and milliseconds() - event.observed_ms < 3600000
                and (policy is None or event.observed_ms >= policy.updated_ms)):
            result = deliver_event(db, event, sub, delivery=delivery)
            decision = db.get(WhaleEventDecision, (delivery.user_id, event.event_key))
            if decision:
                decision.outcome = result
                db.commit()
        else:
            # Removed/paused/obsolete subscriptions must not occupy the retry queue forever.
            notification = db.get(Notification, delivery.notification_id)
            notification.status = "cancelled"
            decision = db.get(WhaleEventDecision, (delivery.user_id, event.event_key))
            if decision:
                decision.outcome = "cancelled"
            db.commit()
