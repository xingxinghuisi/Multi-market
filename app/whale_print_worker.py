import argparse
import asyncio
import json
import os
import time

from collections import (
    deque,
)

from datetime import (
    datetime,
    timedelta,
    timezone,
)

import requests
import websockets

from telegram_service import (
    send_telegram_message,
)


API_BASE_URL = os.getenv(
    "MARKET_RADAR_API_URL",
    "http://127.0.0.1:8000",
).rstrip("/")

BINANCE_WS_BASE = os.getenv(
    "BINANCE_WS_BASE_URL",
    "wss://fstream.binance.com",
).rstrip("/")

REQUEST_TIMEOUT = int(
    os.getenv(
        "WHALE_REQUEST_TIMEOUT",
        "15",
    )
)

# 订阅刷新间隔（秒）：
# 轮询订阅表，发现币种/阈值变化后自动重连 WebSocket。
SUB_REFRESH_SECONDS = int(
    os.getenv(
        "WHALE_SUB_REFRESH_SECONDS",
        "300",
    )
)

DEFAULT_WHALE_MIN_USD = float(
    os.getenv(
        "WHALE_DEFAULT_MIN_USD",
        "50000",
    )
)

DEFAULT_COOLDOWN_SECONDS = int(
    os.getenv(
        "WHALE_DEFAULT_COOLDOWN_SECONDS",
        "300",
    )
)

# 近 N 分钟净流入统计窗口
FLOW_WINDOW_SECONDS = int(
    os.getenv(
        "WHALE_FLOW_WINDOW_SECONDS",
        "300",
    )
)

UTC8 = timezone(
    timedelta(hours=8)
)


def log(message):
    now = datetime.now(
        UTC8
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print(
        f"[WHALE PRINT] "
        f"[{now}] "
        f"{message}",
        flush=True,
    )


def load_subscriptions():
    """从推送订阅表读取 whale_print 订阅。

    返回：
        {symbol: {
            "threshold_usd": float,
            "cooldown_seconds": int,
            "chat_id": str | None,
        }}
    """

    response = requests.get(
        f"{API_BASE_URL}/api/internal/subscriptions",
        params={
            "alert_type":
                "whale_print",
        },
        headers={
            "X-Radar-Worker-Token":
                os.getenv(
                    "RADAR_WORKER_TOKEN",
                    "",
                ),
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(
        data,
        list,
    ):
        raise RuntimeError(
            "Subscriptions API did not "
            "return a list"
        )

    subscriptions = {}
    seen_symbols = set()

    for item in data:

        symbol = str(
            item.get(
                "symbol",
                "",
            )
        ).upper()

        if not symbol:
            continue

        if symbol in seen_symbols:
            continue

        seen_symbols.add(
            symbol
        )

        config = (
            item.get(
                "config"
            )
            or {}
        )

        try:
            threshold_usd = float(
                config.get(
                    "whale_min_usd",
                    DEFAULT_WHALE_MIN_USD,
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            threshold_usd = (
                DEFAULT_WHALE_MIN_USD
            )

        try:
            cooldown_seconds = int(
                config.get(
                    "cooldown_seconds",
                    DEFAULT_COOLDOWN_SECONDS,
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            cooldown_seconds = (
                DEFAULT_COOLDOWN_SECONDS
            )

        subscriptions[symbol] = {
            "threshold_usd":
                threshold_usd,
            "cooldown_seconds":
                max(
                    0,
                    cooldown_seconds,
                ),
            "chat_id":
                item.get(
                    "telegram_chat_id"
                )
                or None,
        }

    return subscriptions


def format_usd(value):
    return f"${value:,.0f}"


def format_qty(value):

    text = f"{value:,.4f}".rstrip(
        "0"
    ).rstrip(
        "."
    )

    return text


def format_flow(value):

    sign = "+" if value >= 0 else "-"

    return f"{sign}{format_usd(abs(value))}"


def build_message(
    symbol,
    is_buy,
    notional,
    qty,
    price,
    net_flow,
):

    direction = (
        "主动买入"
        if is_buy
        else "主动卖出"
    )

    now_text = datetime.now(
        UTC8
    ).strftime(
        "%Y年%m月%d日 %H:%M:%S"
    )

    return (
        f"🐋 {symbol} 大额成交 · "
        f"{direction} "
        f"{format_usd(notional)}\n"
        f"\n"
        f"{format_qty(qty)}张 @ "
        f"{price:g}\n"
        f"📊 近5分钟净流入 "
        f"{format_flow(net_flow)}\n"
        f"\n"
        f"🕐 {now_text}\n"
        f"\n"
        f"Rule #3"
    )


class WhaleWatcher:

    def __init__(
        self,
        subscriptions,
    ):

        self.subscriptions = (
            subscriptions
        )

        # 每币最近成交：
        # deque[(timestamp, notional, is_buy)]
        self.recent_trades = {
            symbol: deque()
            for symbol in subscriptions
        }

        # 每币上次推送时间（冷却）
        self.last_alert_at = {}

    def record_trade(
        self,
        symbol,
        notional,
        is_buy,
        now,
    ):

        trades = self.recent_trades.get(
            symbol
        )

        if trades is None:
            return

        trades.append(
            (
                now,
                notional,
                is_buy,
            )
        )

        cutoff = (
            now
            - FLOW_WINDOW_SECONDS
        )

        while (
            trades
            and trades[0][0] < cutoff
        ):
            trades.popleft()

    def net_flow(
        self,
        symbol,
    ):

        trades = self.recent_trades.get(
            symbol,
            (),
        )

        flow = 0.0

        for (
            _,
            notional,
            is_buy,
        ) in trades:

            flow += (
                notional
                if is_buy
                else -notional
            )

        return flow

    def should_alert(
        self,
        symbol,
        notional,
        now,
    ):

        config = self.subscriptions.get(
            symbol
        )

        if config is None:
            return False

        if notional < config[
            "threshold_usd"
        ]:
            return False

        last = self.last_alert_at.get(
            symbol,
            0,
        )

        if (
            now - last
            < config["cooldown_seconds"]
        ):
            return False

        self.last_alert_at[
            symbol
        ] = now

        return True

    def handle_trade(
        self,
        symbol,
        price,
        qty,
        is_buy,
    ):

        now = time.time()

        notional = (
            price
            * qty
        )

        self.record_trade(
            symbol,
            notional,
            is_buy,
            now,
        )

        if not self.should_alert(
            symbol,
            notional,
            now,
        ):
            return

        config = self.subscriptions[
            symbol
        ]

        message = build_message(
            symbol,
            is_buy,
            notional,
            qty,
            price,
            self.net_flow(
                symbol
            ),
        )

        sent = send_telegram_message(
            message,
            chat_id=config["chat_id"],
        )

        if sent:

            log(
                f"ALERT {symbol} "
                f"{'买' if is_buy else '卖'} "
                f"{format_usd(notional)}"
            )

        else:

            log(
                f"ALERT FAILED {symbol} "
                f"{format_usd(notional)}"
            )


async def watch_forever(
    dry_run=False,
):

    backoff = 5

    while True:

        try:
            subscriptions = (
                load_subscriptions()
            )
        except Exception as error:

            log(
                "Load subscriptions failed | "
                f"{type(error).__name__}: "
                f"{error}"
            )

            await asyncio.sleep(
                backoff
            )

            backoff = min(
                backoff * 2,
                60,
            )

            continue

        if not subscriptions:

            log(
                "No whale_print subscriptions, "
                "waiting..."
            )

            await asyncio.sleep(
                SUB_REFRESH_SECONDS
            )

            continue

        backoff = 5

        try:

            await watch_streams(
                subscriptions,
                dry_run=dry_run,
            )

        except Exception as error:

            log(
                "Stream error | "
                f"{type(error).__name__}: "
                f"{error}"
            )

        log(
            f"Reconnecting in {backoff}s..."
        )

        await asyncio.sleep(
            backoff
        )

        backoff = min(
            backoff * 2,
            60,
        )


async def watch_streams(
    subscriptions,
    dry_run=False,
):

    symbols = sorted(
        subscriptions.keys()
    )

    streams = "/".join(
        f"{symbol.lower()}@aggTrade"
        for symbol in symbols
    )

    url = (
        f"{BINANCE_WS_BASE}/stream"
        f"?streams={streams}"
    )

    log(
        "Subscribing: "
        + ", ".join(symbols)
    )

    watcher = WhaleWatcher(
        subscriptions
    )

    last_refresh = time.time()

    # 断线自动重连由外层 watch_forever 负责。
    async with websockets.connect(
        url,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=10,
    ) as websocket:

        log(
            "WebSocket connected"
        )

        async for raw_message in websocket:

            try:
                payload = json.loads(
                    raw_message
                )
            except ValueError:
                continue

            data = payload.get(
                "data",
                payload,
            )

            if (
                data.get("e")
                != "aggTrade"
            ):
                continue

            symbol = str(
                data.get("s", "")
            ).upper()

            if (
                symbol
                not in subscriptions
            ):
                continue

            try:
                price = float(
                    data.get("p", 0)
                )
                qty = float(
                    data.get("q", 0)
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            if (
                price <= 0
                or qty <= 0
            ):
                continue

            # Binance "m" = 买方是否为 maker。
            # m=true → 买方挂单，卖方主动 → 主动卖出。
            # m=false → 买方主动 → 主动买入。
            is_buy = not bool(
                data.get("m", False)
            )

            if dry_run:

                log(
                    f"DRY {symbol} "
                    f"{'买' if is_buy else '卖'} "
                    f"{format_usd(price * qty)}"
                )

            else:

                watcher.handle_trade(
                    symbol,
                    price,
                    qty,
                    is_buy,
                )

            # 定期刷新订阅：
            # 币种/阈值变化则断开，由外层重连。
            now = time.time()

            if (
                now - last_refresh
                >= SUB_REFRESH_SECONDS
            ):

                last_refresh = now

                try:
                    fresh = (
                        load_subscriptions()
                    )
                except Exception as error:

                    log(
                        "Refresh subscriptions "
                        "failed | "
                        f"{type(error).__name__}: "
                        f"{error}"
                    )

                    continue

                if set(
                    fresh.keys()
                ) != set(
                    subscriptions.keys()
                ):

                    log(
                        "Subscription symbols changed, "
                        "reconnecting..."
                    )

                    return

                # 币种不变、仅阈值/冷却变化：
                # 热更新，无需重连。
                if fresh != subscriptions:

                    log(
                        "Subscription config updated"
                    )

                    subscriptions = fresh

                    watcher.subscriptions = (
                        fresh
                    )


def main():

    parser = (
        argparse.ArgumentParser()
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "只打印收到的成交，"
            "不推送 Telegram"
        ),
    )

    args = parser.parse_args()

    log(
        "Whale Print Worker started"
        + (
            " (dry-run)"
            if args.dry_run
            else ""
        )
    )

    asyncio.run(
        watch_forever(
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
