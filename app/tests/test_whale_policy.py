"""Configurable personal filters, durable aggregation and honest market coverage."""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from hyperliquid_whales import milliseconds, position_event
from models import Notification, User
from whale_models import (WhaleAddress, WhaleAdjustmentBatch, WhaleEventDecision, WhaleMarketAddress,
    WhalePositionDelivery, WhalePositionEvent, WhalePushPolicy, WhaleSubscription, initialize_whale_tables)
from whale_monitoring import market_monitoring
from whale_push_policy import DEFAULT_POLICY, adjustment_metrics, adjustment_passes, clear_pending_for_sub
import whale_position_service as service
import whale_position_worker as worker

A, B = "0x" + "a" * 40, "0x" + "b" * 40
COIN = "xyz:KORU"


@pytest.fixture
def state(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = [milliseconds()]
    sent = []
    monkeypatch.setattr(service, "milliseconds", lambda: now[0])
    monkeypatch.setattr(service, "send_telegram_message", lambda msg, chat_id: sent.append(msg) or True)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    yield factory, now, sent
    engine.dispose()


def subscription(db, username="owner", coin=COIN, cooldown=0, **policy):
    user = db.scalar(select(User).where(User.username == username))
    if not user:
        user = User(username=username, telegram_chat_id="synthetic-target")
        db.add(user); db.flush()
    sub = WhaleSubscription(user_id=user.id, coin=coin, started_ms=0, cooldown_seconds=cooldown)
    db.add(sub); db.flush()
    db.add(WhalePushPolicy(subscription_id=sub.id, data={**DEFAULT_POLICY, **policy}, updated_ms=0))
    db.commit()
    return sub


def position(qty, stamp):
    return {"qty": str(qty), "notional_usd": str(abs(Decimal(str(qty))) * 20),
        "entry_price": "19.5", "leverage": "3", "leverage_type": "isolated", "snapshot_ms": stamp}


def event(db, before, after, stamp, address=A, coin=COIN, price="20", gap=10000):
    payload = position_event(address, coin, position(before, stamp-gap) if before is not None else None,
                             position(after, stamp), stamp)
    if price is not None:
        payload["execution"] = {"status": "verified", "price": price, "fill_count": 1,
                                "start_ms": stamp-gap+1, "end_ms": stamp}
    row = WhalePositionEvent(event_key=payload["event_key"], address=address, coin=coin,
        kind=payload["kind"], qualifying_usd=float(payload["qualifying_usd"]), observed_ms=stamp, payload=payload)
    db.add(row); db.commit()
    return row


@pytest.mark.parametrize("settings,expected", [
    ({"min_change_usd": 5000, "min_change_pct": 0}, False),
    ({"min_change_usd": 0, "min_change_pct": .5}, False),
    ({"min_change_usd": 0, "min_change_pct": 0}, True),
])
def test_both_personal_gates_and_zero_disables_each_gate(state, settings, expected):
    factory, now, sent = state
    with factory() as db:
        sub = subscription(db, aggregation_seconds=0, **settings)
        change = event(db, -100000, -100080.1, now[0])
        assert service.process_event(db, change, sub) == ("sent" if expected else "below_change")
        assert len(sent) == int(expected)


def test_quantity_percentage_and_execution_not_position_entry_price(state):
    factory, now, _ = state
    with factory() as db:
        payload = event(db, 100000, 100500, now[0], price="10").payload
        metrics = adjustment_metrics(payload)
        assert metrics == {"usd": Decimal("5000"), "pct": Decimal(".5"), "basis": "fills"}
        assert adjustment_passes(payload, DEFAULT_POLICY)
        payload.pop("execution")
        assert adjustment_metrics(payload)["usd"] == 10000
        assert adjustment_metrics(payload)["basis"] == "snapshot_estimate"


def test_small_changes_merge_after_restart_and_send_one_weighted_average(state):
    factory, now, sent = state
    with factory() as db:
        sub = subscription(db)
        first = event(db, 100000, 100100, now[0], price="20")
        assert service.process_event(db, first, sub) == "buffering"
        sub_id, first_key = sub.id, first.event_key
    # A new session represents restarting delivery; no in-memory buffer is required.
    with factory() as db:
        sub = db.get(WhaleSubscription, sub_id)
        assert service.process_event(db, db.get(WhalePositionEvent, first_key), sub) == "buffering"
        now[0] += 10000
        second = event(db, 100100, 100300, now[0], price="22")
        assert service.process_event(db, second, sub) == "buffering"
        now[0] += 10000
        third = event(db, 100300, 100600, now[0], price="24")
        assert service.process_event(db, third, sub) == "sent"
        assert len(sent) == 1 and "累计加仓 600" in sent[0] and "（成交均价）" in sent[0]
        assert "$22.66666667" in sent[0] and "–" in sent[0] and len(sent[0].splitlines()) == 7
        assert db.scalars(select(WhaleAdjustmentBatch)).all() == []
        assert db.get(WhaleEventDecision, (sub.user_id, first_key)).outcome == "merged"
        service.deliver_pending(db)
        assert len(sent) == 1


def test_unknown_fill_price_in_one_member_never_yields_partial_execution_average(state):
    factory, now, sent = state
    with factory() as db:
        sub = subscription(db)
        assert service.process_event(db, event(db, 100000, 100200, now[0], price=None), sub) == "buffering"
        now[0] += 10000
        assert service.process_event(db, event(db, 100200, 100600, now[0]), sub) == "sent"
        assert "加仓价格：未提供" in sent[0]


def test_legacy_previous_snapshot_without_time_does_not_break_cumulative_message(state):
    factory, now, sent = state
    with factory() as db:
        sub = subscription(db)
        first = event(db, 100000, 100200, now[0], price=None)
        first.payload = {**first.payload, "previous_snapshot_ms": None}
        db.commit()
        assert service.process_event(db, first, sub) == "buffering"
        now[0] += 10000
        assert service.process_event(db, event(db, 100200, 100600, now[0]), sub) == "sent"
        assert "累计加仓 600" in sent[0] and "加仓价格：未提供" in sent[0]


def test_expired_small_batch_is_filtered_and_does_not_join_next_window(state):
    factory, now, sent = state
    with factory() as db:
        sub = subscription(db, aggregation_seconds=30)
        first = event(db, 100000, 100300, now[0])
        service.deliver_pending(db)
        now[0] += 31000
        second = event(db, 100300, 100600, now[0], gap=31000)
        service.deliver_pending(db)
        assert sent == []
        assert db.get(WhaleEventDecision, (sub.user_id, first.event_key)).outcome == "below_change"
        assert db.get(WhaleEventDecision, (sub.user_id, second.event_key)).outcome == "buffering"
        now[0] += 31000
        service.deliver_pending(db)
        assert db.scalars(select(WhaleAdjustmentBatch)).all() == []


@pytest.mark.parametrize("after", [0, -100000])
def test_close_and_reverse_bypass_cooldown_and_cancel_micro_batch(state, after):
    factory, now, sent = state
    with factory() as db:
        sub = subscription(db, cooldown=300)
        assert service.process_event(db, event(db, None, 100000, now[0]), sub) == "sent"
        now[0] += 10000
        assert service.process_event(db, event(db, 100000, 100100, now[0]), sub) == "buffering"
        now[0] += 10000
        major = event(db, 100100, after, now[0])
        assert service.process_event(db, major, sub) == "sent"
        assert service.process_event(db, major, sub) == "sent"  # Recorded outcome, no second delivery.
        assert len(sent) == 2 and db.scalars(select(WhaleAdjustmentBatch)).all() == []


def test_open_priority_can_be_disabled_and_normal_cooldown_still_applies(state):
    factory, now, sent = state
    with factory() as db:
        sub = subscription(db, cooldown=300, priority_events=False)
        service.process_event(db, event(db, None, 100000, now[0]), sub)
        now[0] += 10000
        assert service.process_event(db, event(db, 0, 100000, now[0]), sub) == "cooldown"
        assert len(sent) == 1


def test_new_opening_bypasses_cooldown_when_priority_is_enabled(state):
    factory, now, sent = state
    with factory() as db:
        sub = subscription(db, cooldown=300)
        service.process_event(db, event(db, None, 100000, now[0]), sub)
        now[0] += 10000
        assert service.process_event(db, event(db, 0, 100000, now[0]), sub) == "sent"
        assert len(sent) == 2


def test_qualified_batch_waits_for_cooldown_and_flushes_without_another_trade(state):
    factory, now, sent = state
    with factory() as db:
        sub = subscription(db, cooldown=30)
        service.process_event(db, event(db, None, 100000, now[0]), sub)
        now[0] += 10000
        change = event(db, 100000, 101000, now[0])
        assert service.process_event(db, change, sub) == "buffering"
        change.dispatched_ms = now[0]; db.commit()
        now[0] += 31000
        service.flush_batches(db)
        assert len(sent) == 2
        assert db.get(WhaleEventDecision, (sub.user_id, change.event_key)).outcome == "sent"


def test_direction_change_does_not_merge_and_unchanged_poll_gap_can_merge(state):
    factory, now, sent = state
    with factory() as db:
        sub = subscription(db)
        first = event(db, 100000, 100300, now[0])
        service.process_event(db, first, sub)
        now[0] += 20000  # An intervening unchanged snapshot advances the previous snapshot time.
        second = event(db, 100300, 100600, now[0], gap=10000)
        assert service.process_event(db, second, sub) == "sent"
        now[0] += 10000
        small = event(db, 100600, 100700, now[0])
        service.process_event(db, small, sub)
        now[0] += 10000
        assert service.process_event(db, event(db, 100700, 100500, now[0]), sub) == "buffering"
        assert db.get(WhaleEventDecision, (sub.user_id, small.event_key)).outcome == "superseded"
        assert len(sent) == 1


def test_buffers_and_personal_gates_are_isolated_across_users_wallets_markets(state):
    factory, now, sent = state
    with factory() as db:
        strict = subscription(db)
        loose = subscription(db, username="other", min_change_usd=0, min_change_pct=0)
        gold = subscription(db, coin="xyz:GOLD")
        first = event(db, 100000, 100300, now[0])
        assert service.process_event(db, first, strict) == "buffering"
        assert service.process_event(db, first, loose) == "sent"
        assert service.process_event(db, event(db, 100000, 100300, now[0], address=B), strict) == "buffering"
        assert service.process_event(db, event(db, 100000, 100300, now[0], coin="xyz:GOLD"), gold) == "buffering"
        assert len(sent) == 1 and len(db.scalars(select(WhaleAdjustmentBatch)).all()) == 3
        clear_pending_for_sub(db, strict.id); db.commit()
        assert len(db.scalars(select(WhaleAdjustmentBatch)).all()) == 1


def test_policy_change_cancels_failed_delivery_retry(state, monkeypatch):
    factory, now, sent = state
    monkeypatch.setattr(service, "send_telegram_message", lambda *a, **k: False)
    with factory() as db:
        sub = subscription(db)
        change = event(db, 100000, 101000, now[0])
        assert service.process_event(db, change, sub) == "failed"
        delivery = db.scalars(select(WhalePositionDelivery)).one()
        delivery.next_retry_ms = 0
        db.get(WhalePushPolicy, sub.id).updated_ms = now[0] + 1
        db.commit(); service.deliver_pending(db)
        assert db.get(Notification, delivery.notification_id).status == "cancelled"
        assert db.get(WhaleEventDecision, (sub.user_id, change.event_key)).outcome == "cancelled"


def test_market_discovery_is_bounded_and_coverage_does_not_attribute_every_wallet_to_every_coin(state):
    factory, now, _ = state
    trade = {"coin": COIN, "px": "20", "sz": "1", "time": now[0], "users": [A, B]}
    assert worker.remember_trades([trade], {COIN}, 1)[0] == 1
    with factory() as db:
        assert [(m.coin, m.address) for m in db.scalars(select(WhaleMarketAddress))] == [(COIN, A)]
        sub, gold = subscription(db), subscription(db, coin="xyz:GOLD")
        row = db.get(WhaleAddress, A)
        row.positions = {COIN: position(100000, now[0]-240000)}
        row.checked_ms = now[0]; row.snapshot_ms = now[0]-240000
        db.commit()
        change = event(db, 100000, 100100, now[0])
        service.process_event(db, change, sub)
        other = subscription(db, username="other")
        service.record_decision(db, change, other, "sent"); db.commit()
        monitored = market_monitoring(db, sub.user_id, [sub, gold], [row], now[0])
        assert monitored[0]["known_addresses"] == monitored[0]["verified_addresses"] == 1
        assert monitored[0]["eligible_positions"] == monitored[0]["stale_positions"] == 1
        assert monitored[0]["outcomes_24h"] == {"buffering": 1}
        assert monitored[1]["known_addresses"] == 0


def test_additive_initialization_preserves_legacy_subscription_and_defaults(state):
    factory, _, _ = state
    engine = factory.kw["bind"]
    for table in [WhalePushPolicy, WhaleAdjustmentBatch, WhaleEventDecision, WhaleMarketAddress]:
        table.__table__.drop(engine)
    with factory() as db:
        user = User(username="legacy"); db.add(user); db.flush()
        db.add(WhaleSubscription(user_id=user.id, coin=COIN, started_ms=123))
        db.commit()
    initialize_whale_tables(engine)
    initialize_whale_tables(engine)
    with factory() as db:
        sub = db.scalars(select(WhaleSubscription)).one()
        assert sub.started_ms == 123
        assert service.policy_for(db, sub) == DEFAULT_POLICY
