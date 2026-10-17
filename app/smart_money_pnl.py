"""Binance-page-style valuation of sampled cohorts, not account settlement PnL."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext

from sqlalchemy import select

from models import MarketQuote
from subscription_service import supports_subscription

MAX_QUOTE_AGE = 120
MAX_SNAPSHOT_AGE = 900
MAX_COMPARISON_GAP = 1800
MAX_VALUE = Decimal("1e30")


def utc_time(value):
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    # Existing SQLite provider times are stored as naive UTC.
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)


def decimal(value, *, signed=False):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not result.is_finite() or abs(result) > MAX_VALUE or (not signed and result < 0):
        return None
    return result


def calculate(quantity, entry, price, is_long):
    qty, avg, current = decimal(quantity), decimal(entry), decimal(price)
    if qty is None or current is None or current <= 0:
        return None
    if qty == 0:
        return 0.0
    if avg is None or avg <= 0:
        return None
    with localcontext() as context:
        context.prec = 64
        value = (current - avg) * qty * (1 if is_long else -1)
    return float(value) if abs(value) <= MAX_VALUE else None


def value_snapshot(snapshot, asset, quote, now=None):
    """Return a copy: never contaminate the shared source cache with a user's valuation."""
    now = now or datetime.now(timezone.utc)
    result = deepcopy(snapshot)
    market = f"binance:usdm:{asset.symbol}"
    valuation = {"status": "unavailable", "reason": "missing_quote", "basis": "latest_trade",
                 "asset_id": asset.id, "market": market, "currency": "USDT", "price": None,
                 "quote_at": None, "snapshot_at": snapshot.get("fetched_at"),
                 "calculated_at": now.isoformat(), "max_quote_age_seconds": MAX_QUOTE_AGE,
                 "max_snapshot_age_seconds": MAX_SNAPSHOT_AGE, "sides": {}}
    result["pnl"] = valuation
    if not supports_subscription(asset) or not asset.enabled or snapshot.get("market") != market:
        valuation["reason"] = "market_mismatch"
        return result
    if snapshot.get("refresh_error"):
        valuation["reason"] = "source_error"
        return result
    try:
        age = (now - utc_time(snapshot["fetched_at"])).total_seconds()
        if age < -60 or age > MAX_SNAPSHOT_AGE:
            valuation["reason"] = "stale_snapshot"
            return result
    except (TypeError, ValueError, KeyError, OverflowError):
        valuation["reason"] = "invalid_snapshot_time"
        return result
    if quote is None:
        return result
    if quote.asset_id != asset.id:
        valuation["reason"] = "market_mismatch"
        return result
    try:
        stamp = utc_time(quote.event_time)
        age = (now - stamp).total_seconds()
        valuation["quote_at"] = stamp.isoformat()
        if age < -60 or age > MAX_QUOTE_AGE:
            valuation["reason"] = "stale_quote"
            return result
    except (TypeError, ValueError, OverflowError):
        valuation["reason"] = "invalid_quote_time"
        return result
    price = decimal(quote.price)
    if price is None or price <= 0:
        valuation["reason"] = "invalid_price"
        return result
    valuation["price"] = float(price)
    for side in ("long", "short"):
        values = snapshot.get("sides", {}).get(side, {})
        valuation["sides"][side] = {
            "traders_usdt": calculate(values.get("quantity"), values.get("avg_entry_price"), price, side == "long"),
            "whales_usdt": calculate(values.get("whale_quantity"), values.get("whale_avg_entry_price"), price, side == "long"),
        }
    complete = [value for values in valuation["sides"].values() for value in values.values()]
    valuation["status"] = "ok" if all(value is not None for value in complete) else "partial"
    valuation["reason"] = None if valuation["status"] == "ok" else "missing_fields"
    return result


def attach_valuation(db, asset, snapshot, now=None):
    quote = db.scalar(select(MarketQuote).where(MarketQuote.asset_id == asset.id))
    return value_snapshot(snapshot, asset, quote, now)


def pnl_comparison(before, after):
    """Compare only valid, forward observations of the same market and pricing basis."""
    first, last = (item.get("pnl") or {} for item in (before or {}, after))
    if (first.get("status") not in {"ok", "partial"} or last.get("status") not in {"ok", "partial"}
            or first.get("market") != last.get("market")
            or first.get("currency") != "USDT" or last.get("currency") != "USDT"
            or first.get("basis") != "latest_trade" or last.get("basis") != "latest_trade"):
        return None
    try:
        gap = (utc_time(after["fetched_at"]) - utc_time(before["fetched_at"])).total_seconds()
        if not 0 < gap <= MAX_COMPARISON_GAP:
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    sides = {}
    for side in ("long", "short"):
        sides[side] = {}
        for cohort in ("traders_usdt", "whales_usdt"):
            old = decimal(first.get("sides", {}).get(side, {}).get(cohort), signed=True)
            new = decimal(last.get("sides", {}).get(side, {}).get(cohort), signed=True)
            with localcontext() as context:
                context.prec = 64
                value = new - old if old is not None and new is not None else None
            sides[side][cohort] = float(value) if value is not None and abs(value) <= MAX_VALUE else None
    return {"before_observed_at": before["fetched_at"], "after_observed_at": after["fetched_at"],
            "before_quote_at": first.get("quote_at"), "after_quote_at": last.get("quote_at"),
            "basis": "latest_trade", "currency": "USDT", "sides": sides}
