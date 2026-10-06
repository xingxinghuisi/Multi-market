"""Read public USD-M futures metrics without persisting or inventing values."""

import math
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import HTTPException


_cache = {}
_lock = threading.Lock()
_TTL_SECONDS = 20


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _timestamp(value):
    try:
        milliseconds = int(value)
        if milliseconds <= 0:
            return None
        return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def get_futures_metrics(asset, read_json):
    if not (asset.enabled and asset.venue == "BINANCE" and
            asset.asset_type == "crypto" and
            re.search(r"FUTURES|PERPETUAL", asset.segment, re.I)):
        raise HTTPException(status_code=404, detail="Futures metrics not available for this asset")

    symbol = asset.symbol.upper()
    if not re.fullmatch(r"[A-Z0-9]{2,50}", symbol):
        raise HTTPException(status_code=422, detail="Invalid Binance symbol")

    cache_key = (asset.id, symbol)
    with _lock:
        cached = _cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < (5 if cached[1]["unavailable"] else _TTL_SECONDS):
            return cached[1]

    result = {
        "asset_id": asset.id, "symbol": symbol, "source": "Binance USD-M Futures",
        "mark_price": None, "index_price": None, "last_funding_rate": None,
        "next_funding_time": None, "premium_time": None,
        "open_interest": None, "open_interest_time": None, "unavailable": [],
    }
    base = "https://fapi.binance.com"
    symbol_query = urlencode({"symbol": symbol})
    try:
        premium = read_json(f"{base}/fapi/v1/premiumIndex?{symbol_query}")
        if not isinstance(premium, dict) or premium.get("symbol") != symbol:
            raise ValueError("Unexpected premium index response")
        result["mark_price"] = _number(premium.get("markPrice"))
        result["index_price"] = _number(premium.get("indexPrice"))
        result["last_funding_rate"] = _number(premium.get("lastFundingRate"))
        result["next_funding_time"] = _timestamp(premium.get("nextFundingTime"))
        result["premium_time"] = _timestamp(premium.get("time"))
    except Exception:
        result["unavailable"].append("premium_index")

    try:
        interest = read_json(f"{base}/fapi/v1/openInterest?{symbol_query}")
        if not isinstance(interest, dict) or interest.get("symbol") != symbol:
            raise ValueError("Unexpected open interest response")
        result["open_interest"] = _number(interest.get("openInterest"))
        result["open_interest_time"] = _timestamp(interest.get("time"))
    except Exception:
        result["unavailable"].append("open_interest")

    # Cache partial failures briefly to avoid hammering an unavailable upstream.
    with _lock:
        _cache[cache_key] = (time.monotonic(), result)
    return result
