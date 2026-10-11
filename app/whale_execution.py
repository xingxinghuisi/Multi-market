"""Match public fills to snapshot changes; never infer execution from entry/mark prices."""
from decimal import Decimal, localcontext

from hyperliquid_whales import decimal

MAX_FILL_WINDOW_MS = 3600000
FILL_LIMIT = 2000


def fill_window(event):
    start, end = event.get("previous_snapshot_ms"), event.get("snapshot_ms")
    if (event["kind"] != "discovered" and type(start) is int and type(end) is int
            and 0 < start < end and end - start <= MAX_FILL_WINDOW_MS):
        return start + 1, end
    return None


def execution_details(event, raw):
    """Require a complete, one-direction fill chain connecting both signed quantities.

    Multiple fills use size-weighted prices. A reversal splits each crossing fill
    at zero into closing/opening quantities. Mixed buys/sells cannot identify a
    unique execution price for a net snapshot change, so remain unavailable.
    """
    unavailable = {"status": "unavailable", "reason": "no_baseline"}
    window = fill_window(event)
    if window is None:
        return unavailable
    if not isinstance(raw, list):
        return {**unavailable, "reason": "fills_unavailable"}
    if len(raw) >= FILL_LIMIT:
        return {**unavailable, "reason": "response_limit"}
    try:
        return _match(event, raw, window)
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return {**unavailable, "reason": "invalid_fills"}


def _match(event, raw, window):
    def missing(reason):
        return {"status": "unavailable", "reason": reason}

    # Bounds below keep all quantity/value arithmetic exact within this context.
    with localcontext() as ctx:
        ctx.prec = 80
        old, new = decimal(event["previous_qty"]), decimal(event["qty"])
        if old == new:
            return missing("no_quantity_change")
        direction = Decimal(1) if new > old else Decimal(-1)
        expected_side = "B" if direction > 0 else "A"
        fills = {}
        for row in raw:
            if not isinstance(row, dict):
                return missing("invalid_fills")
            if row.get("coin") != event["coin"]:
                continue
            stamp, tid = row["time"], row["tid"]
            if type(stamp) is not int or type(tid) is not int or tid < 0:
                return missing("invalid_fills")
            if not window[0] <= stamp <= window[1]:
                continue
            size, price, start = decimal(row["sz"]), decimal(row["px"]), decimal(row["startPosition"])
            if not (0 < size <= Decimal("1e30") and 0 < price <= Decimal("1e18") and abs(start) <= Decimal("1e30")):
                return missing("invalid_fills")
            if row["side"] not in {"B", "A"}:
                return missing("invalid_fills")
            if row["side"] != expected_side:
                return missing("mixed_directions")
            fill = (stamp, start, size, price)
            if tid in fills and fills[tid] != fill:
                return missing("conflicting_fills")
            fills[tid] = fill
        if not fills:
            return missing("no_matching_fills")

        running = old
        close_qty = close_value = open_qty = open_value = Decimal(0)
        close_count = open_count = 0
        # Trade IDs need not be chronological. Within a timestamp, a monotonic
        # position chain is ordered by startPosition in the execution direction.
        for stamp, start, size, price in sorted(fills.values(), key=lambda f: (f[0], f[1] * direction)):
            if start != running:
                return missing("quantity_mismatch")
            closing = min(abs(running), size) if running * direction < 0 else Decimal(0)
            opening = size - closing
            close_qty += closing
            close_value += closing * price
            open_qty += opening
            open_value += opening * price
            close_count += closing > 0
            open_count += opening > 0
            running += direction * size
        if running != new:
            return missing("quantity_mismatch")
        details = {"status": "verified", "basis": "fills_vwap", "fill_count": len(fills),
                   "start_ms": window[0], "end_ms": window[1]}
        if event["kind"] == "flipped":
            if close_qty != abs(old) or open_qty != abs(new):
                return missing("quantity_mismatch")
            return {**details, "close_price": str(close_value / close_qty),
                    "open_price": str(open_value / open_qty),
                    "close_fill_count": close_count, "open_fill_count": open_count}
        if event["kind"] in {"opened", "increased"}:
            if close_qty != 0 or open_qty != abs(new - old):
                return missing("mixed_actions")
            price = open_value / open_qty
        else:
            if open_qty != 0 or close_qty != abs(new - old):
                return missing("mixed_actions")
            price = close_value / close_qty
        return {**details, "price": str(price)}
