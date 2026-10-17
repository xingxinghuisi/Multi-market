"""Valuation math, stale-source handling and same-market isolation; no network."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_money_pnl import calculate, pnl_comparison, value_snapshot

NOW = datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc)
ASSET = SimpleNamespace(id=2, symbol="KORUUSDT", asset_type="crypto", venue="BINANCE",
                        segment="FUTURES", currency="USDT", enabled=True)


def snapshot():
    return {"market": "binance:usdm:KORUUSDT", "fetched_at": NOW.isoformat(),
            "source_updated_at": (NOW-timedelta(hours=8)).isoformat(),
            "sides": {"long": {"quantity": 100, "avg_entry_price": 10,
                               "whale_quantity": 75, "whale_avg_entry_price": 10},
                      "short": {"quantity": 200, "avg_entry_price": 15,
                                "whale_quantity": 150, "whale_avg_entry_price": 15}}}


def quote(price=12, **kwargs):
    return SimpleNamespace(**{"asset_id": 2, "price": price, "event_time": NOW, **kwargs})


CASES = json.loads(Path(__file__).with_name("fixtures").joinpath("smart-money-pnl.json").read_text())


@pytest.mark.parametrize("case", CASES)
def test_shared_valuation_contract(case):
    result = calculate(case["quantity"], case["entry"], case["price"], case["long"])
    if case["expected"] is None:
        assert result is None
    else:
        assert result == pytest.approx(case["expected"], abs=1e-9)


@pytest.mark.parametrize("qty,entry,price", [(float("nan"), 10, 12), (100, float("inf"), 12),
                                            (100, 10, float("nan")), (1e30, 1, 1e30)])
def test_invalid_or_unbounded_amounts_do_not_reach_notifications(qty, entry, price):
    assert calculate(qty, entry, price, True) is None


def test_valuation_keeps_quote_and_snapshot_times_separate_and_cache_immutable():
    raw = snapshot()
    original = deepcopy(raw)
    result = value_snapshot(raw, ASSET, quote(event_time=NOW.replace(tzinfo=None)), NOW)
    assert raw == original and "pnl" not in raw
    assert result["pnl"]["status"] == "ok"
    assert result["pnl"]["basis"] == "latest_trade"
    assert result["pnl"]["sides"] == {"long": {"traders_usdt": 200, "whales_usdt": 150},
                                       "short": {"traders_usdt": 600, "whales_usdt": 450}}
    assert result["pnl"]["quote_at"].endswith("+00:00")
    assert result["source_updated_at"] != result["pnl"]["quote_at"]


@pytest.mark.parametrize("change,reason", [
    ({"quote": None}, "missing_quote"),
    ({"quote": quote(asset_id=1)}, "market_mismatch"),  # Spot with the same display symbol.
    ({"quote": quote(event_time=NOW-timedelta(seconds=121))}, "stale_quote"),
    ({"quote": quote(event_time=NOW+timedelta(seconds=61))}, "stale_quote"),
    ({"quote": quote(event_time=None)}, "invalid_quote_time"),
    ({"quote": quote(price=float("nan"))}, "invalid_price"),
    ({"snapshot": {**snapshot(), "market": "xyz:KORU"}}, "market_mismatch"),
    ({"snapshot": {**snapshot(), "fetched_at": (NOW-timedelta(seconds=901)).isoformat()}}, "stale_snapshot"),
    ({"snapshot": {**snapshot(), "refresh_error": "unavailable"}}, "source_error"),
])
def test_bad_inputs_hide_money_without_erasing_the_source_snapshot(change, reason):
    data = change.get("snapshot", snapshot())
    result = value_snapshot(data, ASSET, change.get("quote", quote()), NOW)
    assert result["pnl"]["reason"] == reason
    assert result["pnl"]["sides"] == {}
    assert result["sides"] == data["sides"]


def test_partial_missing_is_distinct_from_zero_and_does_not_hide_the_other_side():
    data = snapshot()
    data["sides"]["long"]["whale_quantity"] = None
    data["sides"]["short"]["whale_quantity"] = 0
    data["sides"]["short"]["whale_avg_entry_price"] = None
    result = value_snapshot(data, ASSET, quote(), NOW)["pnl"]
    assert result["status"] == "partial"
    assert result["sides"]["long"]["whales_usdt"] is None
    assert result["sides"]["short"]["whales_usdt"] == 0
    assert result["sides"]["long"]["traders_usdt"] == 200


def test_snapshot_pnl_delta_is_not_realized_profit_and_survives_old_checkpoints():
    before = value_snapshot(snapshot(), ASSET, quote(), NOW)
    later = NOW+timedelta(minutes=10)
    new = {**snapshot(), "fetched_at": later.isoformat()}
    after = value_snapshot(new, ASSET, quote(price=13, event_time=later), later)
    comparison = pnl_comparison(before, after)
    assert comparison["sides"]["long"]["whales_usdt"] == 75
    assert comparison["sides"]["short"]["whales_usdt"] == -150
    assert comparison["before_quote_at"] == NOW.isoformat()
    assert comparison["after_quote_at"] == later.isoformat()
    assert pnl_comparison(snapshot(), after) is None  # Pre-upgrade JSON has no valuation.
    assert pnl_comparison(before, before) is None  # Re-reading the same source cache.
    assert pnl_comparison(before, {**after, "fetched_at": (NOW+timedelta(seconds=1801)).isoformat()}) is None
    mismatched = deepcopy(after)
    mismatched["pnl"]["market"] = "xyz:KORU"
    assert pnl_comparison(before, mismatched) is None
    mismatched = deepcopy(after)
    mismatched["pnl"]["currency"] = "BTC"
    assert pnl_comparison(before, mismatched) is None
