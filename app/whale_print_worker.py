"""Observe Binance USD-M aggregated trades and fan out to account-owned subscriptions."""
import argparse
import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
import json
import math
import os
import time

import websockets

from subscription_client import load_subscriptions as load_rows, submit_event

BINANCE_WS_BASE = os.getenv("BINANCE_WS_BASE_URL", "wss://fstream.binance.com").rstrip("/")
SUB_REFRESH_SECONDS = 15
FLOW_WINDOW_SECONDS = 300
UTC8 = timezone(timedelta(hours=8))


def log(message):
    print(f"[WHALE] {message}", flush=True)


def load_subscriptions():
    grouped = {}
    for row in load_rows("whale_print"):
        grouped.setdefault(row["symbol"], []).append(row)
    return grouped


def build_message(symbol, is_buy, notional, qty, price, net_flow, event_time, observed_seconds):
    direction = "主动买入" if is_buy else "主动卖出"
    stamp = datetime.fromtimestamp(event_time / 1000, UTC8).strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"🐋 {symbol} 大额成交 · {direction} ${notional:,.0f}\n\n"
        f"成交价：{price:g} USDT\n数量：{qty:g}（Binance 原始数量）\n"
        f"已观测主动买卖差额：{net_flow:+,.0f} USDT\n"
        f"统计窗口：最近 {observed_seconds} 秒（最多 5 分钟）\n\n"
        f"🕐 {stamp}\n"
        "来源：Binance USD-M 聚合成交；不代表单个钱包或真实资金净流入。"
    )


class WhaleWatcher:
    def __init__(self, subscriptions):
        self.subscriptions = subscriptions
        self.recent_trades = {}
        self.observed_since = {}
        self.flow_totals = {}
        self.last_alert_at = {}
        self.last_trade_id = {}
        self.retry_after = {}

    def replace_subscriptions(self, subscriptions):
        self.subscriptions = subscriptions
        active_ids = {row["subscription_id"] for rows in subscriptions.values() for row in rows}
        for mapping in (self.last_alert_at, self.retry_after):
            for key in list(mapping):
                if key not in active_ids:
                    del mapping[key]
        for mapping in (self.recent_trades, self.observed_since, self.flow_totals, self.last_trade_id):
            for symbol in list(mapping):
                if symbol not in subscriptions:
                    del mapping[symbol]

    def reset_flow(self):
        # A disconnected interval is missing data; never present it as a complete 5-minute window.
        self.recent_trades.clear()
        self.observed_since.clear()
        self.flow_totals.clear()

    def handle_trade(self, data, dry_run=False):
        symbol = str(data.get("s", "")).upper()
        rows = tuple(self.subscriptions.get(symbol, ()))
        if data.get("e") != "aggTrade" or not rows:
            return
        try:
            price, qty = float(data["p"]), float(data["q"])
            trade_id, event_time = int(data["a"]), int(data["T"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return
        notional = price * qty
        if not all(math.isfinite(v) and v > 0 for v in (price, qty, notional)) or event_time <= 0 or trade_id < 0:
            return
        if trade_id <= self.last_trade_id.get(symbol, -1):
            return
        self.last_trade_id[symbol] = trade_id
        now = time.monotonic()
        is_buy = not bool(data.get("m", False))
        trades = self.recent_trades.setdefault(symbol, deque())
        self.observed_since.setdefault(symbol, now)
        amount = notional if is_buy else -notional
        trades.append((now, amount))
        self.flow_totals[symbol] = self.flow_totals.get(symbol, 0) + amount
        while trades and trades[0][0] < now - FLOW_WINDOW_SECONDS:
            self.flow_totals[symbol] -= trades.popleft()[1]
        flow = self.flow_totals[symbol]
        observed = min(FLOW_WINDOW_SECONDS, max(1, int(now - self.observed_since[symbol])))
        message = build_message(symbol, is_buy, notional, qty, price, flow, event_time, observed)
        for row in rows:
            config = row["config"]
            sub_id = row["subscription_id"]
            if (notional < config["whale_min_usd"]
                    or now - self.last_alert_at.get(sub_id, -float("inf")) < config["cooldown_seconds"]
                    or now < self.retry_after.get(sub_id, 0)):
                continue
            if dry_run:
                log(f"DRY subscription={sub_id} {message}")
                continue
            try:
                result = submit_event(sub_id, f"whale:{symbol}:{trade_id}",
                                      message.split("\n", 1)[0], message, notional_usd=notional)
                status = result.get("status")
                if status in {"sent", "in_app", "pending", "cooldown", "duplicate"}:
                    self.last_alert_at[sub_id] = now
                elif status == "failed":
                    self.retry_after[sub_id] = now + 5
                log(f"subscription={sub_id} {symbol} status={status}")
            except Exception as error:
                # Avoid a request storm when the API is unavailable. Do not consume the user's cooldown.
                self.retry_after[sub_id] = now + 5
                log(f"Delivery error: {type(error).__name__}")


async def watch_streams(watcher, dry_run=False):
    symbols = set(watcher.subscriptions)
    streams = "/".join(f"{symbol.lower()}@aggTrade" for symbol in sorted(symbols))
    url = f"{BINANCE_WS_BASE}/stream?streams={streams}"
    watcher.reset_flow()
    next_refresh = time.monotonic() + SUB_REFRESH_SECONDS
    async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=10) as socket:
        log(f"Connected: {', '.join(sorted(symbols))}")
        while True:
            if time.monotonic() >= next_refresh:
                fresh = await asyncio.to_thread(load_subscriptions)
                watcher.replace_subscriptions(fresh)
                if set(fresh) != symbols:
                    return
                next_refresh = time.monotonic() + SUB_REFRESH_SECONDS
            try:
                raw = await asyncio.wait_for(socket.recv(), timeout=max(.01, next_refresh - time.monotonic()))
            except asyncio.TimeoutError:
                continue  # Refresh even when the market is quiet.
            try:
                payload = json.loads(raw)
                data = payload.get("data", payload)
                if not isinstance(data, dict):
                    continue
            except (ValueError, AttributeError):
                continue
            await asyncio.to_thread(watcher.handle_trade, data, dry_run)


async def watch_forever(dry_run=False):
    watcher = WhaleWatcher({})
    while True:
        try:
            watcher.replace_subscriptions(await asyncio.to_thread(load_subscriptions))
            if not watcher.subscriptions:
                await asyncio.sleep(SUB_REFRESH_SECONDS)
                continue
            await watch_streams(watcher, dry_run)
        except Exception as error:
            log(f"Stream error: {type(error).__name__}")
            await asyncio.sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(watch_forever(args.dry_run))


if __name__ == "__main__":
    main()
