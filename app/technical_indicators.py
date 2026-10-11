"""Deterministic indicators over validated, consecutive, CLOSED Binance USD-M candles."""
import math
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

INTERVAL_MS = {"15m": 900000, "1h": 3600000, "4h": 14400000, "1d": 86400000}


class TechnicalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    timeframe: Literal["15m", "1h", "4h", "1d"] = "1h"
    indicators: list[Literal["rsi", "macd", "ma", "kdj", "volume", "fibonacci", "divergence"]] = Field(
        default_factory=lambda: ["rsi", "macd", "ma", "kdj", "volume"], min_length=1, max_length=7)
    rsi_low: float = Field(default=30, gt=0, lt=100)
    rsi_high: float = Field(default=70, gt=0, lt=100)
    ma_type: Literal["EMA", "MA"] = "EMA"
    ma_fast: int = Field(default=9, ge=2, le=99)
    ma_slow: int = Field(default=21, ge=3, le=100)
    volume_multiple: float = Field(default=2, ge=1.1, le=100)
    fib_low: float | None = Field(default=None, gt=0, le=1e12)
    fib_high: float | None = Field(default=None, gt=0, le=1e12)
    fib_trend: Literal["up", "down"] = "up"
    fib_tolerance_pct: float = Field(default=0.3, gt=0, le=5)
    cooldown_seconds: int = Field(default=3600, ge=0, le=86400)
    ai_enabled: bool = True

    @model_validator(mode="after")
    def valid_ranges(self):
        if self.rsi_low >= self.rsi_high or self.ma_fast >= self.ma_slow:
            raise ValueError("RSI 下限须小于上限，均线短周期须小于长周期")
        if len(set(self.indicators)) != len(self.indicators):
            raise ValueError("指标不能重复")
        if "fibonacci" in self.indicators and (
                self.fib_low is None or self.fib_high is None or self.fib_low >= self.fib_high):
            raise ValueError("斐波那契需要明确的高低锚点，且低点小于高点")
        return self


def closed_candles(rows, timeframe, now_ms):
    if not isinstance(rows, list):
        raise ValueError("Binance candle list unavailable")
    step = INTERVAL_MS[timeframe]
    candles = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 8:
            raise ValueError("Malformed candle")
        start, end = int(row[0]), int(row[6])
        if end >= now_ms:
            continue
        op, high, low, close, volume, notional = [float(row[i]) for i in (1, 2, 3, 4, 5, 7)]
        if (not all(math.isfinite(v) for v in (op, high, low, close, volume, notional))
                or min(op, high, low, close) <= 0 or min(volume, notional) < 0
                or high < max(op, close) or low > min(op, close) or low > high
                or start < 0 or start % step != 0 or end != start + step - 1):
            raise ValueError("Invalid candle values")
        if candles and start != candles[-1]["start"] + step:
            raise ValueError("Candle gap or duplicate")
        candles.append(dict(start=start, end=end, open=op, high=high, low=low, close=close,
                            volume=volume, notional=notional))
    # Disallow a stale earlier candle standing in for the latest complete period.
    expected_end = (now_ms // step) * step - 1
    if len(candles) < 150 or candles[-1]["end"] != expected_end:
        raise ValueError("Insufficient or stale closed candles")
    return candles


def sma(values, period):
    return [None if i + 1 < period else sum(values[i + 1 - period:i + 1]) / period
            for i in range(len(values))]


def ema(values, period):
    result, previous, seed = [], None, []
    for value in values:
        if value is None:
            result.append(None)
            continue
        if previous is None:
            seed.append(value)
            if len(seed) < period:
                result.append(None)
                continue
            previous = sum(seed) / period
        else:
            previous += (value - previous) * 2 / (period + 1)
        result.append(previous)
    return result


def rsi(values, period=14):
    result = [None] * len(values)
    gains, losses = [], []
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
        if i < period:
            continue
        if i == period:
            gain, loss = sum(gains) / period, sum(losses) / period
        else:
            gain = (gain * (period - 1) + gains[-1]) / period
            loss = (loss * (period - 1) + losses[-1]) / period
        result[i] = 50.0 if gain == loss == 0 else 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return result


def indicator_series(candles, config):
    closes = [r["close"] for r in candles]
    r = rsi(closes)
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [None if a is None or b is None else a - b for a, b in zip(e12, e26)]
    dea = ema(dif, 9)
    average = ema if config.ma_type == "EMA" else sma
    fast, slow = average(closes, config.ma_fast), average(closes, config.ma_slow)
    k_values, d_values, j_values = [], [], []
    k = d = 50.0
    for i, row in enumerate(candles):
        if i < 8:
            k_values.append(None); d_values.append(None); j_values.append(None)
            continue
        low = min(c["low"] for c in candles[i - 8:i + 1])
        high = max(c["high"] for c in candles[i - 8:i + 1])
        rsv = 50 if high == low else 100 * (row["close"] - low) / (high - low)
        k, d = (2 * k + rsv) / 3, (2 * d + (2 * k + rsv) / 3) / 3
        k_values.append(k); d_values.append(d); j_values.append(3 * k - 2 * d)
    return dict(rsi=r, dif=dif, dea=dea, ma_fast=fast, ma_slow=slow, k=k_values, d=d_values, j=j_values)


def evaluate(candles, config):
    series = indicator_series(candles, config)
    latest, previous = candles[-1], candles[-2]
    values = {key: rows[-1] for key, rows in series.items()}
    signals = []

    def cross(name, old, new, boundary=0):
        if old is None or new is None:
            return
        if old <= boundary < new:
            signals.append(f"{name}上穿" if boundary == 0 else f"{name}上穿 {boundary:g}")
        elif old >= boundary > new:
            signals.append(f"{name}下穿" if boundary == 0 else f"{name}下穿 {boundary:g}")

    if "rsi" in config.indicators:
        for boundary in (config.rsi_low, config.rsi_high):
            cross("RSI14 ", series["rsi"][-2], values["rsi"], boundary)
    for indicator, a, b, name in (("macd", "dif", "dea", "MACD DIF/DEA "),
                                 ("ma", "ma_fast", "ma_slow", f"{config.ma_type}{config.ma_fast}/{config.ma_slow} "),
                                 ("kdj", "k", "d", "KDJ K/D ")):
        if indicator in config.indicators:
            old, new = series[a][-2] - series[b][-2], values[a] - values[b]
            count = len(signals)
            cross(name, old, new)
            if len(signals) > count:
                signals[-1] = signals[-1].replace("上穿", "金叉").replace("下穿", "死叉")
    mean_volume = sum(c["notional"] for c in candles[-21:-1]) / 20
    previous_mean = sum(c["notional"] for c in candles[-22:-2]) / 20
    ratio = latest["notional"] / mean_volume if mean_volume else None
    old_ratio = previous["notional"] / previous_mean if previous_mean else None
    if ("volume" in config.indicators and ratio is not None and old_ratio is not None
            and old_ratio < config.volume_multiple <= ratio):
        signals.append(f"成交额放大至前 20 根均值的 {ratio:.2f} 倍")
    levels = {}
    if "fibonacci" in config.indicators:
        span = config.fib_high - config.fib_low
        for retracement in (0.382, 0.5, 0.618):
            level = config.fib_high - span * retracement if config.fib_trend == "up" else config.fib_low + span * retracement
            levels[str(retracement)] = level
            near = abs(latest["close"] / level - 1) * 100 <= config.fib_tolerance_pct
            was_near = abs(previous["close"] / level - 1) * 100 <= config.fib_tolerance_pct
            if previous["close"] <= level < latest["close"] or previous["close"] >= level > latest["close"]:
                direction = "突破" if latest["close"] > level else "跌破"
                signals.append(f"斐波那契 {retracement} {direction} ${level:.6g}")
            elif near and not was_near:
                signals.append(f"接近斐波那契 {retracement} ${level:.6g}")
    if "divergence" in config.indicators:
        # RSI divergence on strict pivots confirmed by three following closed candles.
        # Signal only when the second pivot is confirmed NOW; no future look-ahead.
        for side in ("low", "high"):
            pivots = [i for i in range(3, len(candles) - 3) if all(
                (candles[i][side] < candles[j][side] if side == "low" else candles[i][side] > candles[j][side])
                for j in range(i - 3, i + 4) if j != i) and series["rsi"][i] is not None]
            if len(pivots) >= 2 and pivots[-1] == len(candles) - 4:
                a, b = pivots[-2:]
                if side == "low" and candles[b][side] < candles[a][side] and series["rsi"][b] > series["rsi"][a]:
                    signals.append("RSI 底背离确认（右侧 3 根收盘确认）")
                if side == "high" and candles[b][side] > candles[a][side] and series["rsi"][b] < series["rsi"][a]:
                    signals.append("RSI 顶背离确认（右侧 3 根收盘确认）")
    return {
        "timeframe": config.timeframe, "candle_close_ms": latest["end"],
        "candle_time": datetime.fromtimestamp((latest["end"] + 1) / 1000, timezone.utc).isoformat(),
        "close": latest["close"], "indicators": values, "volume_usdt": latest["notional"],
        "relative_volume": ratio, "fibonacci": levels, "signals": signals,
        "ma_type": config.ma_type, "ma_periods": [config.ma_fast, config.ma_slow],
        "source": "Binance USD-M Futures / closed klines",
        "turnover_rate": None, "turnover_note": "永续合约无股票流通股本换手率；使用成交额和相对成交额。",
    }
