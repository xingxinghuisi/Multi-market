"""Execution prices must come from complete public fills, not snapshot averages."""
from copy import deepcopy
import pytest
from sqlalchemy import select

import hyperliquid_whales as public
from hyperliquid_whales import PublicAPIError, PublicClient, event_text, milliseconds, position_event
from whale_execution import execution_details, fill_window
from whale_models import WhaleAddress, WhalePositionEvent
import whale_position_worker as worker
from test_whale_positions import A, COIN, position, sessions, snapshot

START, END = 100000, 160000


def event(old="-100", new="-168.2"):
    return position_event(A, COIN, {**position(old), "snapshot_ms": START}, position(new), END)


def fill(size="68.2", price="18.14", start="-100", side="A", stamp=120000, tid=1, coin=COIN):
    return {"coin": coin, "sz": size, "px": price, "startPosition": start,
            "side": side, "time": stamp, "tid": tid}


@pytest.mark.parametrize("old,new,side,label", [
    ("-100", "-168.2", "A", "加仓价格"), ("100", "168.2", "B", "加仓价格"),
    ("-100", "-31.8", "B", "减仓价格"), ("100", "31.8", "A", "减仓价格"),
    ("-68.2", "0", "B", "平仓价格"), ("68.2", "0", "A", "平仓价格"),
    ("0", "68.2", "B", "开仓价格"), ("0", "-68.2", "A", "开仓价格"),
])
def test_action_price_uses_fill_not_position_average(old, new, side, label):
    payload = event(old, new)
    payload["execution"] = execution_details(payload, [fill(start=old, side=side)])
    assert payload["execution"]["status"] == "verified"
    assert payload["execution"]["price"] == "18.14"
    text = event_text(payload)[1]
    assert f"{label}：$18.14" in text and "成交均价" not in text
    if new != "0":
        assert "开仓均价：$19.5" in text


def test_multiple_fills_use_volume_weighted_price_and_deduplicate_trade_ids():
    payload = event("-100", "-110")
    first = fill("2", "18", tid=99)
    second = fill("8", "20", start="-102", tid=1)
    # Equal timestamps and non-chronological IDs are resolved by startPosition.
    payload["execution"] = execution_details(payload, [second, first, deepcopy(first)])
    assert payload["execution"]["price"] == "19.6"
    assert payload["execution"]["fill_count"] == 2
    assert "加仓价格：$19.6（成交均价）" in event_text(payload)[1]


@pytest.mark.parametrize("old,new,side", [("-10", "5", "B"), ("10", "-5", "A")])
def test_reversal_splits_closing_and_opening_fills_at_zero(old, new, side):
    payload = event(old, new)
    middle = "-6" if old.startswith("-") else "6"
    payload["execution"] = execution_details(payload, [
        fill("4", "18", start=old, side=side),
        fill("11", "20", start=middle, side=side, tid=2, stamp=130000)])
    assert payload["execution"]["close_price"] == "19.2"
    assert payload["execution"]["open_price"] == "20"
    text = event_text(payload)[1]
    assert "平仓价格：$19.2（成交均价）" in text and "开仓价格：$20\n" in text


@pytest.mark.parametrize("raw,reason", [
    (None, "fills_unavailable"), ({"error": "offline"}, "fills_unavailable"),
    ([], "no_matching_fills"), ([fill(coin="KORUUSDT")], "no_matching_fills"),
    ([fill(stamp=START)], "no_matching_fills"), ([fill(stamp=END+1)], "no_matching_fills"),
    ([fill(start="-101")], "quantity_mismatch"), ([fill(size="68")], "quantity_mismatch"),
    ([fill(side="B")], "mixed_directions"), ([fill(price="NaN")], "invalid_fills"),
    ([fill(price="0")], "invalid_fills"), ([fill(size="-1")], "invalid_fills"),
    ([fill(side="bad")], "invalid_fills"), ([fill(stamp=True)], "invalid_fills"),
    ([fill(tid="1")], "invalid_fills"), ([None], "invalid_fills"),
    ([fill(), fill(price="18.15")], "conflicting_fills"),
    ([fill()] * 2000, "response_limit"),
])
def test_missing_incomplete_or_invalid_fills_never_invent_execution(raw, reason):
    payload = event()
    payload["execution"] = execution_details(payload, raw)
    assert payload["execution"] == {"status": "unavailable", "reason": reason}
    assert "加仓价格：未提供" in event_text(payload)[1]


def test_mixed_buy_and_sell_fills_cannot_be_labeled_as_net_addition_price():
    # Net +10 short, but two distinct actions in between the snapshots.
    raw = [fill("20", "18"), fill("10", "20", start="-120", side="B", tid=2, stamp=130000)]
    assert execution_details(event("-100", "-110"), raw)["reason"] == "mixed_directions"


def test_discovery_old_baselines_and_legacy_events_remain_unavailable():
    discovered = position_event(A, COIN, None, position(), END)
    assert fill_window(discovered) is None
    assert execution_details(discovered, [fill()])["status"] == "unavailable"
    assert "开仓价格：未提供" in event_text(discovered)[1]
    payload = event()
    assert "加仓价格：未提供" in event_text(payload)[1]
    payload["previous_snapshot_ms"] = END-3600001
    assert fill_window(payload) is None


def test_public_fill_query_is_bounded_unaggregated_and_keeps_xyz_names(monkeypatch):
    client, requests = PublicClient(), []
    monkeypatch.setattr(client, "info", lambda payload: requests.append(payload) or [])
    assert client.fills(A, START+1, END) == []
    assert requests == [{"type": "userFillsByTime", "user": A, "startTime": START+1,
                         "endTime": END, "aggregateByTime": False}]


def test_public_rest_budget_includes_fill_response_weight(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(public.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(public.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    class Response:
        status_code = 200
        def json(self):
            return [{}] * 2000
    client, calls = PublicClient(), []
    monkeypatch.setattr(client.session, "post", lambda *a, **k: calls.append(clock[0]) or Response())
    client.fills(A, START, END)
    client.positions(A)
    client.positions(A)
    assert calls == [0.0, 8.0, 8.6]  # weight (20 + 2000/20) / 15, then 0.6s


@pytest.mark.parametrize("failure", [None, PublicAPIError(429, 120), RuntimeError("offline")])
def test_worker_fill_lookup_does_not_lose_snapshot_or_change_on_failure(sessions, failure):
    now = milliseconds()
    old = {**position("-100000"), "snapshot_ms": now-60000}
    with sessions() as db:
        db.add(WhaleAddress(address=A, discovered_ms=1, last_trade_ms=now, next_check_ms=0,
                           positions={COIN: old}, snapshot_ms=old["snapshot_ms"]))
        db.commit()
    class Client:
        calls = []
        def positions(self, address):
            return snapshot("-100068.2", now)
        def fills(self, address, start, end):
            self.calls.append((address, start, end))
            if failure:
                raise failure
            return [fill(start="-100000", stamp=now-1)]
    client = Client()
    result = worker.scan_one(client, {COIN: 1000000})
    assert result["last_scan_error"] is None
    assert client.calls == [(A, old["snapshot_ms"]+1, now)]
    with sessions() as db:
        assert db.get(WhaleAddress, A).positions[COIN]["qty"] == "-100068.2"
        payload = db.scalars(select(WhalePositionEvent)).one().payload
        assert payload["kind"] == "increased"
        assert payload["execution"]["status"] == ("unavailable" if failure else "verified")
        if not failure:
            assert payload["execution"]["price"] == "18.14"
        elif isinstance(failure, PublicAPIError):
            assert result["scan_retry_ms"] >= now+120000


def test_worker_discovery_and_price_only_change_do_not_request_fills(sessions):
    class Client:
        stamp = milliseconds()
        def positions(self, _):
            return snapshot(stamp=self.stamp)
        def fills(self, *args):
            pytest.fail("No fill lookup for discovery or unchanged quantities")
    client = Client()
    with sessions() as db:
        db.add(WhaleAddress(address=A, discovered_ms=1, last_trade_ms=1, next_check_ms=0, positions={}))
        db.commit()
    worker.scan_one(client, {COIN: 1000000})
    with sessions() as db:
        db.get(WhaleAddress, A).next_check_ms = 0
        db.commit()
    client.stamp += 1
    worker.scan_one(client, {COIN: 1000000})
    with sessions() as db:
        assert len(db.scalars(select(WhalePositionEvent)).all()) == 1


def test_worker_multiple_changed_markets_share_one_fill_request(sessions):
    now, second_coin = milliseconds(), "xyz:GOLD"
    with sessions() as db:
        previous = {coin: {**position("-100000"), "snapshot_ms": now-60000}
                    for coin in [COIN, second_coin]}
        db.add(WhaleAddress(address=A, discovered_ms=1, last_trade_ms=now, next_check_ms=0,
                           positions=previous, snapshot_ms=now-60000))
        db.commit()
    class Client:
        calls = 0
        def positions(self, _):
            raw = snapshot("-100068.2", now)
            extra = deepcopy(raw["assetPositions"][0])
            extra["position"]["coin"] = second_coin
            raw["assetPositions"].append(extra)
            return raw
        def fills(self, *args):
            self.calls += 1
            return [fill(start="-100000", stamp=now-1, coin=coin, tid=i)
                    for i, coin in enumerate([COIN, second_coin])]
    client = Client()
    worker.scan_one(client, {COIN: 1000000, second_coin: 1000000})
    assert client.calls == 1
    with sessions() as db:
        events = db.scalars(select(WhalePositionEvent)).all()
        assert len(events) == 2
        assert all(row.payload["execution"]["price"] == "18.14" for row in events)
