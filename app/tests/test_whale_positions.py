"""Public wallet discovery and truthful classification; isolated DB, no external sends."""
from copy import deepcopy

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from hyperliquid_whales import (PublicClient, address_value, event_text, milliseconds,
                                parse_positions, position_event)
from models import Notification, User
from whale_models import (WhaleAddress, WhalePositionDelivery, WhalePositionEvent,
                          WhaleSubscription, initialize_whale_tables)
import whale_position_service as service
import whale_position_worker as worker

A = "0x" + "a" * 40
B = "0x" + "b" * 40
COIN = "xyz:KORU"


def position(qty="100000", value="2000000", entry="19.5", leverage="10"):
    return {"qty": qty, "notional_usd": value, "entry_price": entry,
            "leverage": leverage, "leverage_type": "isolated"}


def snapshot(qty="100000", stamp=None):
    return {"time": stamp or milliseconds(), "assetPositions": [{"position": {
        "coin": COIN, "szi": qty, "positionValue": str(abs(float(qty)) * 20),
        "entryPx": "19.5", "leverage": {"type": "isolated", "value": 10}}}]}


@pytest.fixture
def sessions(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(service, "CHAT_ID", "deployment-target")
    monkeypatch.setattr(service, "send_telegram_message", lambda *a, **k: pytest.fail("Unexpected Telegram send"))
    yield factory
    engine.dispose()


@pytest.mark.parametrize("bad", ["", "BTCUSDT", "0x123", "0x" + "0" * 40, None])
def test_invalid_wallets_are_not_candidates(bad):
    assert address_value(bad) is None
    assert address_value(A.upper().replace("0X", "0x")) == A


def test_first_snapshot_is_discovery_and_price_only_change_is_not_increase():
    initial = position_event(A, COIN, None, position(), milliseconds())
    assert initial["kind"] == "discovered"
    assert initial["previous_qty"] is None
    assert position_event(A, COIN, position(), position(value="3000000"), milliseconds()) is None
    title, text = event_text(initial)
    assert title == "🐋 KORU 新发现已有多单"
    assert text.splitlines()[0] == title and len(text.splitlines()) == 6
    assert "开仓均价：$19.5｜10x 逐仓" in text and "MIRAO" not in text
    assert "trade.xyz" in text and "北京时间" in text
    assert A not in text and f"地址：{A[:8]}…{A[-6:]}" in text


@pytest.mark.parametrize("source,expected,display", [
    ("1234.50", "1234.50", "+$1,234.50"),
    ("-987.65", "-987.65", "-$987.65"), ("0", "0", "$0.00"),
    (None, None, "未提供"), ("NaN", None, "未提供"), ("1e400", None, "未提供"),
])
def test_unrealized_pnl_uses_source_value_without_inventing_missing_profit(source, expected, display):
    raw = snapshot()
    raw["assetPositions"][0]["position"]["unrealizedPnl"] = source
    stamp, positions = parse_positions(raw, [COIN])
    current = positions[COIN]
    assert current["unrealized_pnl"] == expected
    event = position_event(A, COIN, None, current, stamp)
    assert event["unrealized_pnl"] == expected
    assert f"浮动盈亏：{display}" in event_text(event)[1]
    # Mark-to-market P&L changes alone must not trigger a new position event.
    assert position_event(A, COIN, current, {**current,"unrealized_pnl":"5000"}, stamp+1) is None


def test_old_snapshots_and_closures_do_not_invent_realized_profit():
    stamp, positions = parse_positions(snapshot(), [COIN, "xyz:GOLD"])
    assert positions[COIN]["unrealized_pnl"] is None
    assert positions["xyz:GOLD"]["unrealized_pnl"] is None
    closed = position_event(A, COIN, {**position(),"unrealized_pnl":"1234"},
                            {**position("0","0"),"unrealized_pnl":"0"}, stamp)
    assert closed["unrealized_pnl"] is None
    message = event_text(closed)[1]
    assert "已实现盈亏：未提供" in message
    assert "浮动盈亏" not in message


@pytest.mark.parametrize("before,after,kind,side", [
    ("0", "100000", "opened", "long"), ("100000", "120000", "increased", "long"),
    ("100000", "50000", "reduced", "long"), ("100000", "0", "closed", "long"),
    ("100000", "-100000", "flipped", "short"), ("-100000", "-120000", "increased", "short"),
    ("-100000", "0", "closed", "short"),
])
def test_signed_quantity_transitions(before, after, kind, side):
    old = position(before, str(abs(float(before)) * 20))
    new = position(after, str(abs(float(after)) * 20))
    result = position_event(A, COIN, old, new, milliseconds())
    assert result["kind"] == kind and result["side"] == side
    assert float(result["qualifying_usd"]) >= 2000000
    title, text = event_text(result)
    if kind in {"increased", "reduced"}:
        assert title.endswith(str(abs(abs(int(after))-abs(int(before)))))
        assert "剩余仓位：" in text
    if kind == "closed":
        assert title.endswith("平仓") and "上次仓位：" in text
    if kind == "flipped":
        assert "多单转空单" in title


@pytest.mark.parametrize("change", [
    lambda r: r.pop("assetPositions"), lambda r: r.update(time=0),
    lambda r: r["assetPositions"][0]["position"].update(szi="NaN"),
    lambda r: r["assetPositions"][0]["position"].update(positionValue="-100"),
    lambda r: r["assetPositions"][0]["position"].update(positionValue="0"),
    lambda r: r["assetPositions"][0]["position"].update(positionValue="1e400"),
    lambda r: r["assetPositions"].append(deepcopy(r["assetPositions"][0])),
])
def test_malformed_snapshots_never_become_closures(change):
    raw = snapshot()
    change(raw)
    with pytest.raises(ValueError):
        parse_positions(raw, [COIN])


def test_small_public_trade_discovers_both_sides_and_pool_is_bounded(sessions):
    trade = {"coin": COIN, "px": "20", "sz": "0.1", "time": milliseconds(), "users": [A, B]}
    dropped, stamp = worker.remember_trades([trade, trade], {COIN}, 1)
    assert dropped == 1 and stamp == trade["time"]
    with sessions() as db:
        rows = db.scalars(select(WhaleAddress)).all()
        assert len(rows) == 1 and rows[0].address == A
    worker.remember_trades([{**trade, "coin": "KORUUSDT"}], {COIN}, 2)
    with sessions() as db:
        assert len(db.scalars(select(WhaleAddress)).all()) == 1


def test_snapshot_persistence_restart_dedup_and_failure_preserves_position(sessions):
    worker.remember_trades([{"coin": COIN, "px": "20", "sz": "1", "time": milliseconds(), "users": [A, A]}], {COIN}, 100)
    class Client:
        raw = snapshot()
        def positions(self, _address):
            return deepcopy(self.raw)
    client = Client()
    assert worker.scan_one(client, {COIN: 1000000})["last_scan_error"] is None
    with sessions() as db:
        assert db.scalars(select(WhalePositionEvent)).one().kind == "discovered"
        row = db.get(WhaleAddress, A)
        baseline = deepcopy(row.positions)
        row.next_check_ms = 0
        db.commit()
    # The same exchange snapshot cannot generate a second event after a restart.
    assert worker.scan_one(client, {COIN: 1000000})["last_scan_error"] == "Stale snapshot"
    client.raw = {"error": "rate limited"}
    with sessions() as db:
        db.get(WhaleAddress, A).next_check_ms = 0
        db.commit()
    assert worker.scan_one(client, {COIN: 1000000})["last_scan_error"] == "Missing assetPositions"
    with sessions() as db:
        assert db.get(WhaleAddress, A).positions == baseline
        assert len(db.scalars(select(WhalePositionEvent)).all()) == 1


def stored_event(db, address=A, stamp=None):
    payload = position_event(address, COIN, None, position(), stamp or milliseconds())
    row = WhalePositionEvent(event_key=payload["event_key"], address=address, coin=COIN,
        kind=payload["kind"], qualifying_usd=float(payload["qualifying_usd"]),
        observed_ms=milliseconds(), payload=payload)
    db.add(row)
    db.commit()
    return row


def test_account_delivery_dedup_and_personal_target(sessions, monkeypatch):
    sent = []
    monkeypatch.setattr(service, "send_telegram_message", lambda msg, chat_id: sent.append((msg, chat_id)) or True)
    with sessions() as db:
        u = User(username="personal", telegram_chat_id="personal-target")
        other = User(username="no_target")
        db.add_all([u, other]); db.flush()
        subs = [WhaleSubscription(user_id=user.id, coin=COIN, enabled=True,
            min_position_usd=1000000, cooldown_seconds=300, started_ms=0) for user in (u, other)]
        db.add_all(subs); db.commit()
        event = stored_event(db)
        assert service.deliver_event(db, event, subs[0]) == "sent"
        assert service.deliver_event(db, event, subs[0]) == "duplicate"
        assert service.deliver_event(db, event, subs[1]) == "in_app"
        assert [s[1] for s in sent] == ["personal-target"]
        assert len(db.scalars(select(Notification)).all()) == 2
        # A second wallet is not suppressed by the first wallet's cooldown.
        assert service.deliver_event(db, stored_event(db, B), subs[0]) == "sent"


def test_failed_delivery_stops_after_three_attempts_and_checks_enabled(sessions, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "send_telegram_message", lambda *a, **k: calls.append(1) and False)
    with sessions() as db:
        u = User(username="target", telegram_chat_id="personal")
        db.add(u); db.flush()
        sub = WhaleSubscription(user_id=u.id, coin=COIN, enabled=True, min_position_usd=1000000,
                                cooldown_seconds=0, started_ms=0)
        db.add(sub); db.commit()
        event = stored_event(db)
        assert service.deliver_event(db, event, sub) == "failed"
        delivery = db.scalars(select(WhalePositionDelivery)).one()
        sub.enabled = False; db.commit()
        assert service.deliver_event(db, event, sub, delivery) == "inactive"
        sub.enabled = True; db.commit()
        assert service.deliver_event(db, event, sub, delivery) == "failed"
        assert service.deliver_event(db, event, sub, delivery) == "failed"
        assert service.deliver_event(db, event, sub, delivery) == "inactive"
        assert len(calls) == 3


def test_metadata_discovers_all_xyz_markets_and_filters_delisted_other_dexes(monkeypatch):
    client = PublicClient()
    monkeypatch.setattr(client, "info", lambda _: {"universe": [
        {"name": COIN, "maxLeverage": 10}, {"name": "xyz:NVDA", "isDelisted": True},
        {"name": "xyz:GOLD"}, {"name": "BTC"}, {"name": "other:AAPL"},
        {"name": "xyz:New.Contract-1"}, {"name": "xyz:GOLD"}, {"name": "xyz:<bad>"},
        None, {"name": None}]})
    markets = client.markets()
    assert [m["coin"] for m in markets] == ["xyz:GOLD", COIN, "xyz:New.Contract-1"]
    gold = markets[0]
    assert gold["name"] == "GOLD 永续合约" and "股票" not in gold["name"]
    assert markets[1]["name"] == "韩国股票 ETF 关联永续"


def test_additive_table_initialization_keeps_existing_users(sessions):
    with sessions() as db:
        db.add(User(username="preserved")); db.commit()
    initialize_whale_tables(sessions.kw["bind"])
    initialize_whale_tables(sessions.kw["bind"])
    with sessions() as db:
        assert db.scalars(select(User)).one().username == "preserved"


def test_rate_limit_backoff_keeps_baseline(sessions):
    from hyperliquid_whales import PublicAPIError
    with sessions() as db:
        db.add(WhaleAddress(address=A, discovered_ms=1, last_trade_ms=1, next_check_ms=0,
            positions={COIN:position()}, snapshot_ms=milliseconds()-60000))
        db.commit()
    class RateLimited:
        def positions(self, _):
            raise PublicAPIError(429, 120)
    now = milliseconds()
    result = worker.scan_one(RateLimited(), {COIN:1000000})
    assert result["scan_retry_ms"] >= now+120000
    with sessions() as db:
        assert db.get(WhaleAddress,A).positions[COIN]["qty"] == "100000"
        assert db.scalars(select(WhalePositionEvent)).all() == []


def test_deleted_subscription_cancels_failed_delivery_without_blocking_retry_queue(sessions, monkeypatch):
    monkeypatch.setattr(service,"send_telegram_message",lambda *a,**k:False)
    with sessions() as db:
        user=User(username="retry_target",telegram_chat_id="target")
        db.add(user); db.flush()
        sub=WhaleSubscription(user_id=user.id,coin=COIN,started_ms=0,cooldown_seconds=0)
        db.add(sub); db.commit()
        event=stored_event(db)
        assert service.deliver_event(db,event,sub)=="failed"
        delivery=db.scalars(select(WhalePositionDelivery)).one()
        delivery.next_retry_ms=0
        db.delete(sub); db.commit()
        service.deliver_pending(db)
        assert db.get(Notification,delivery.notification_id).status=="cancelled"
