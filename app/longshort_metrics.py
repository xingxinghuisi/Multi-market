"""Expose the existing hourly Binance report data to asset details."""
import threading
import time

from fastapi import HTTPException

from crypto_metrics_worker import fetch_metrics, ratio_value
from subscription_service import supports_subscription

_cache = {}
_lock = threading.Lock()


def get_longshort_metrics(asset, read_json):
    if not supports_subscription(asset):
        raise HTTPException(status_code=404, detail="仅支持 Binance USDT 合约多空数据")
    with _lock:
        cached = _cache.get(asset.symbol)
        if cached and time.monotonic() - cached[0] < (5 if cached[1] is None else 60):
            if cached[1] is None:
                raise HTTPException(status_code=503, detail="完整 1H 多空数据暂不可用，请稍后重试")
            return {**cached[1], "asset_id": asset.id}
    try:
        data = fetch_metrics(asset.symbol, read_json=read_json)
        values = {}
        for key, field in (("global", "longShortRatio"), ("top_account", "longShortRatio"),
                           ("top_position", "longShortRatio"), ("taker", "buySellRatio")):
            values[key] = {"current": ratio_value(data[f"{key}_current"], field),
                           "previous": ratio_value(data[f"{key}_previous"], field)}
        result = {"symbol": asset.symbol, "source": "Binance USD-M Futures", "period": "1h",
                  "hour_start": data["hour_start"].isoformat(), "hour_end": data["hour_end"].isoformat(),
                  "ratios": values,
                  "long_account_pct": ratio_value(data["global_current"], "longAccount") * 100,
                  "short_account_pct": ratio_value(data["global_current"], "shortAccount") * 100}
    except Exception:
        with _lock:
            _cache[asset.symbol] = (time.monotonic(), None)
        raise HTTPException(status_code=503, detail="完整 1H 多空数据暂不可用，请稍后重试") from None
    with _lock:
        _cache[asset.symbol] = (time.monotonic(), result)
    return {**result, "asset_id": asset.id}
