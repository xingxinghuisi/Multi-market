"""Synthetic public data only: source isolation, truthful units and execution proof."""
from copy import deepcopy
import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from hyperliquid_whales import PublicAPIError, event_text, milliseconds, position_event
from lighter_whales import (LighterClient, execution_fill, normalize_trade, parse_account,
                             parse_markets, stream_trades)
from models import Notification, User
from whale_execution import execution_details
from whale_models import WhaleAddress, WhalePositionEvent, WhaleRuntime, WhaleSubscription
from whale_sources import account_index, market_identity
import whale_position_service as service
import whale_position_worker as worker

COIN = "lighter:mainnet:226"
KEY = "lighter:mainnet:1234"
WALLET = "0x" + "a" * 40
MARKETS = {COIN: {"coin": COIN, "symbol": "KORU"}}


def account(qty="100000", sign=-1):
    return {"code": 200, "total": 1, "accounts": [{"code": 0, "account_index": 1234,
        "l1_address": WALLET, "transaction_time": 1, "positions": [{"market_id": 226,
        "symbol": "KORU", "sign": sign, "position": qty, "position_value": str(Decimal(qty) * 20),
        "avg_entry_price": "19.5", "initial_margin_fraction": "5.00", "margin_mode": 1,
        "unrealized_pnl": "1234.50"}]}]}


def trade(stamp=None, **changes):
    return {"market_id": 226, "market_kind": "perps", "trade_id": 99,
            "timestamp": stamp or milliseconds(), "transaction_time": 1,
            "size": "10", "price": "20", "ask_account_id": 1234,
            "bid_account_id": 5678, "is_maker_ask": True,
            "maker_position_size_before": "-100000", "taker_position_size_before": "0", **changes}


@pytest.fixture
def sessions(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    monkeypatch.setattr(service, "send_telegram_message", lambda *a, **k: pytest.fail("External send"))
    yield factory
    engine.dispose()


def test_live_catalog_semantics_include_reduce_only_but_exclude_spot_inactive_hidden():
    item = {"market_id": 226, "symbol": "KORU", "status": "active", "market_type": "perp",
            "market_config": {"force_reduce_only": True}, "daily_quote_token_volume": "0"}
    raw = {"code": 200, "order_book_details": [item, {**item, "market_id": 110, "symbol": "NVDA"},
        {**item, "market_id": 143, "status": "inactive"}, {**item, "market_type": "spot"},
        {**item, "market_config": {"hidden": True}}]}
    markets = parse_markets(raw)
    assert {m["symbol"] for m in markets} == {"KORU", "NVDA"}
    koru = next(m for m in markets if m["coin"] == COIN)
    assert koru["reduce_only"] and koru["volume_24h_usd"] == "0"
    assert market_identity(COIN, markets)["symbol"] == "KORU"
    with pytest.raises(ValueError):
        parse_markets({"code": 200})
    with pytest.raises(ValueError):
        parse_markets({"code": 200, "order_book_details": [item, item]})


def test_position_units_wallet_and_observation_time():
    stamp, result = parse_account(account(), KEY, MARKETS, milliseconds())
    p = result[COIN]
    assert stamp > 1 and p["snapshot_ms"] == stamp  # Last account tx is NOT snapshot time.
    assert p["qty"] == "-100000" and p["notional_usd"] == "2000000"
    assert Decimal(p["leverage"]) == 20 and p["leverage_type"] == "isolated"
    assert p["leverage_basis"] == "initial_margin_fraction"
    assert p["wallet_address"] == WALLET and p["account_index"] == 1234
    assert p["unrealized_pnl"] == "1234.50" and p["snapshot_basis"] == "observed_at"
    raw = account("0")
    raw["accounts"][0]["l1_address"] = "0x" + "0" * 40
    p = parse_account(raw, KEY, MARKETS, stamp)[1][COIN]
    assert p["wallet_address"] is None and p["unrealized_pnl"] is None and p["entry_price"] is None


@pytest.mark.parametrize("change", [
    lambda r: r.update(total=2), lambda r: r.update(code=500), lambda r: r.update(next_cursor="more"),
    lambda r: r["accounts"][0].update(account_index=9876),
    lambda r: r["accounts"][0].pop("positions"),
    lambda r: r["accounts"][0]["positions"].append(deepcopy(r["accounts"][0]["positions"][0])),
    lambda r: r["accounts"][0]["positions"][0].update(position="NaN"),
    lambda r: r["accounts"][0]["positions"][0].update(sign=0),
    lambda r: r["accounts"][0]["positions"][0].update(position_value="0"),
    lambda r: r["accounts"][0]["positions"][0].update(symbol="OTHER"),
])
def test_incomplete_or_invalid_account_never_becomes_a_close(change):
    raw = account()
    change(raw)
    with pytest.raises(ValueError):
        parse_account(raw, KEY, MARKETS, milliseconds())


def test_missing_optional_pnl_margin_does_not_erase_verified_quantity():
    raw = account()
    raw["accounts"][0]["positions"][0].update(unrealized_pnl="NaN", initial_margin_fraction=None)
    p = parse_account(raw, KEY, MARKETS, milliseconds())[1][COIN]
    assert p["qty"] == "-100000" and p["unrealized_pnl"] is None and p["leverage"] is None


def test_stream_discovers_both_accounts_and_rejects_invalid_ids_timestamps():
    t = trade()
    normalized = normalize_trade(t)
    assert normalized["users"] == [KEY, "lighter:mainnet:5678"]
    assert normalized["time"] == t["timestamp"]  # Never microsecond transaction_time.
    packet = {"trades": [t, {**t, "ask_account_id": -1}, {**t, "timestamp": milliseconds()+120000}],
              "liquidation_trades": [{**t, "trade_id": 100}]}
    assert len(stream_trades(packet, {COIN})) == 2
    assert stream_trades(packet, {"xyz:KORU"}) == []
    for invalid in ["lighter:robinhood:1234", "lighter:mainnet:001", "lighter:mainnet:-1", "0x123", "lighter:mainnet:281474976710656"]:
        with pytest.raises(ValueError):
            account_index(invalid)


@pytest.mark.parametrize("own_ask,maker_ask,before_field", [
    (True, True, "maker_position_size_before"), (True, False, "taker_position_size_before"),
    (False, True, "taker_position_size_before"), (False, False, "maker_position_size_before")])
def test_fills_use_own_maker_or_taker_position(own_ask, maker_ask, before_field):
    t = trade(ask_account_id=1234 if own_ask else 5678, bid_account_id=5678 if own_ask else 1234,
              is_maker_ask=maker_ask)
    t[before_field] = "100"
    fill = execution_fill(t, KEY)
    assert fill["startPosition"] == "100" and fill["side"] == ("A" if own_ask else "B")
    with pytest.raises(ValueError):
        execution_fill({**t, "ask_account_id": 1234, "bid_account_id": 1234}, KEY)
    t.pop(before_field)
    with pytest.raises(KeyError):
        execution_fill(t, KEY)


def test_verified_execution_requires_complete_chain_not_entry_or_mark_price():
    start = milliseconds() - 1000
    old = parse_account(account(), KEY, MARKETS, start)[1][COIN]
    new = parse_account(account("100030"), KEY, MARKETS, start+1000)[1][COIN]
    event = position_event(KEY, COIN, old, new, start+1000)
    fills = [execution_fill(trade(start+100, size="10", price="20"), KEY),
             execution_fill(trade(start+200, size="20", price="21", trade_id=100,
                                  maker_position_size_before="-100010"), KEY)]
    details = execution_details(event, fills)
    assert details["status"] == "verified" and abs(Decimal(details["price"]) - Decimal(62) / 3) < Decimal("1e-25")
    assert execution_details(event, fills[:1])["status"] == "unavailable"
    assert execution_details(event, [{**fills[0], "startPosition": "-1"}])["status"] == "unavailable"


def test_history_pagination_is_bounded_and_rejects_unsorted_or_incomplete_history(monkeypatch):
    client = LighterClient()
    now = milliseconds()
    pages = iter([{"trades": [trade(now-100)], "next_cursor": "a"},
                  {"trades": [trade(now-2000)], "next_cursor": "b"}])
    monkeypatch.setattr(client, "get", lambda *a, **k: next(pages))
    assert len(client.fills(KEY, now-1000, now)) == 1
    monkeypatch.setattr(client, "get", lambda *a, **k: {"trades": [trade(now)], "next_cursor": "a"})
    with pytest.raises(ValueError, match="pagination"):
        client.fills(KEY, now-1000, now)
    monkeypatch.setattr(client, "get", lambda *a, **k: {"trades": [trade(now-100), trade(now)], "next_cursor": None})
    with pytest.raises(ValueError, match="Unsorted"):
        client.fills(KEY, now-1000, now)
    pages = iter({"trades": [trade(now-i)], "next_cursor": str(i)} for i in range(3))
    monkeypatch.setattr(client, "get", lambda *a, **k: next(pages))
    with pytest.raises(ValueError, match="page limit"):
        client.fills(KEY, now-1000, now)


def test_rest_budget_includes_catalog_account_and_fills_and_backoff(monkeypatch):
    client = LighterClient()
    clock, sleeps, requests = [100.0], [], []
    monkeypatch.setattr("lighter_whales.time.monotonic", lambda: clock[0])
    def sleep(delay):
        sleeps.append(delay)
        clock[0] += delay
    monkeypatch.setattr("lighter_whales.time.sleep", sleep)
    response = SimpleNamespace(status_code=200, headers={}, json=lambda: {"code": 200})
    monkeypatch.setattr(client.session, "get", lambda *a, **k: requests.append((a, k)) or response)
    client.get("orderBookDetails")
    client.get("account", by="index", value=1234)
    client.get("trades", account_index=1234)
    assert len(requests) == 3 and sum(sleeps) == pytest.approx(2.4)
    assert all("Authorization" not in k["headers"] for _, k in requests)
    response.status_code, response.headers = 429, {"Retry-After": "90"}
    with pytest.raises(PublicAPIError) as failure:
        client.get("account")
    assert failure.value.retry_seconds == 90 and "Lighter" in str(failure.value)
    assert client.next_request_at >= clock[0] + 90


def test_candidate_pools_and_config_are_venue_scoped(sessions):
    worker.remember_trades([{**normalize_trade(trade()), "coin": "xyz:KORU", "users": [WALLET, WALLET]}], {"xyz:KORU"}, 1)
    dropped, _ = worker.remember_trades([normalize_trade(trade())], {COIN}, 1, "lighter")
    assert dropped == 1  # Independent capacity: one HL + one Lighter accepted.
    with sessions() as db:
        assert len(db.scalars(select(WhaleAddress)).all()) == 2
        user = User(username="synthetic")
        db.add(user); db.flush()
        db.add_all([WhaleSubscription(user_id=user.id, coin=coin, min_position_usd=1000, started_ms=1)
                    for coin in (COIN, "xyz:KORU")])
        db.commit()
    assert worker.config_and_heartbeat({}) == {"xyz:KORU": 1000}
    assert worker.config_and_heartbeat({}, "lighter") == {COIN: 1000}
    with sessions() as db:
        assert db.get(WhaleRuntime, 1) and db.get(WhaleRuntime, 2)


def test_many_markets_wait_for_ack_and_pace_control_messages(monkeypatch):
    from lighter_position_worker import Worker
    w = Worker()
    w.coins = {f"lighter:mainnet:{i}" for i in range(213)}
    clock, sends = [100.0], []
    monkeypatch.setattr("lighter_position_worker.time.monotonic", lambda: clock[0])
    async def sleep(delay):
        clock[0] += delay
    async def send(packet):
        sends.append((clock[0], json.loads(packet)))
    monkeypatch.setattr("lighter_position_worker.asyncio.sleep", sleep)
    subscribed, acknowledged = set(), set()
    async def run():
        for _ in range(10):
            await w.reconcile(SimpleNamespace(send=send), subscribed, acknowledged)
        assert len(sends) == 20  # Stop until acknowledgments arrive.
        acknowledged.update(subscribed)
        await w.reconcile(SimpleNamespace(send=send), subscribed, acknowledged)
    asyncio.run(run())
    assert len(sends) == 25 and all(b[0]-a[0] >= .3999 for a,b in zip(sends, sends[1:]))


def test_lighter_scan_records_source_metadata_preserves_failure_and_delivers_once(sessions):
    worker.remember_trades([normalize_trade(trade(bid_account_id=1234))], {COIN}, 100, "lighter")
    class Client:
        raw = account()
        def snapshot(self, key, floors):
            assert key == KEY
            return parse_account(self.raw, key, MARKETS, milliseconds())
    client = Client()
    assert worker.scan_one(client, {"xyz:KORU": 1000}) is None
    assert worker.scan_one(client, {COIN: 1000}, "lighter")["last_scan_error"] is None
    with sessions() as db:
        event = db.scalars(select(WhalePositionEvent)).one()
        assert event.address == KEY and event.payload["source"] == "Lighter 主网"
        assert event.payload["symbol"] == "KORU" and event.payload["wallet_address"] == WALLET
        title, message = event_text(event.payload)
        assert title == "🐋 KORU 新发现已有空单" and "Lighter 主网" in message
        assert "初始保证金率折算" in message and "账户 #1234" in message and KEY not in message
        user = User(username="lighter_reader")
        db.add(user); db.flush()
        sub = WhaleSubscription(user_id=user.id, coin=COIN, min_position_usd=1000, started_ms=1)
        db.add(sub); db.commit()
        assert service.deliver_event(db, event, sub) == "in_app"
        assert service.deliver_event(db, event, sub) == "duplicate"
        assert len(db.scalars(select(Notification)).all()) == 1
        row = db.get(WhaleAddress, KEY)
        before = deepcopy(row.positions)
        row.next_check_ms = 0
        db.commit()
    client.raw = {"code": 500}
    assert worker.scan_one(client, {COIN: 1000}, "lighter")["last_scan_error"]
    with sessions() as db:
        assert db.get(WhaleAddress, KEY).positions == before
        assert len(db.scalars(select(WhalePositionEvent)).all()) == 1
