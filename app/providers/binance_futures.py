from __future__ import annotations

import asyncio
import json
import math
import os
import time

from datetime import (
    datetime,
    timedelta,
    timezone,
)

from urllib.parse import urlencode
from urllib.request import (
    ProxyHandler,
    Request,
    build_opener,
    urlopen,
)

import websockets

from websockets_proxy import (
    Proxy,
    proxy_connect,
)

from providers.binance import (
    BinanceSpotProvider,
)


UTC8 = timezone(
    timedelta(hours=8)
)


class BinanceFuturesProvider(
    BinanceSpotProvider
):
    """
    Binance USD-M Futures Provider

    - Binance Futures WebSocket
    - 动态 SUBSCRIBE / UNSUBSCRIBE
    - UTC+8 自然日涨跌
    - 与 Spot 共用 MarketSnapshot
    """

    BASE_URL = (
        "wss://fstream.binance.com/stream"
    )

    REST_BASE_URL = (
        "https://fapi.binance.com"
    )

    # =====================================================
    # Futures Stream
    #
    # Futures 不直接复用 Spot 的：
    #
    # @kline_1d@+08:00
    #
    # 日线基准由 REST 计算 UTC+8 00:00。
    # WebSocket 只负责实时 trade。
    # =====================================================

    @staticmethod
    def build_streams(
        symbols: set[str],
    ) -> list[str]:

        return [
            f"{symbol.lower()}@trade"
            for symbol
            in sorted(symbols)
        ]

    # =====================================================
    # HTTP JSON
    # =====================================================

    @staticmethod
    def _read_json(
        url: str,
    ):

        request = Request(
            url,
            headers={
                "User-Agent":
                    "Market-Radar/1.0",
            },
        )

        proxy_url = os.getenv(
            "BINANCE_PROXY_URL"
        )

        if proxy_url:

            opener = build_opener(
                ProxyHandler(
                    {
                        "http":
                            proxy_url,

                        "https":
                            proxy_url,
                    }
                )
            )

            with opener.open(
                request,
                timeout=15,
            ) as response:

                return json.loads(
                    response
                    .read()
                    .decode("utf-8")
                )

        with urlopen(
            request,
            timeout=15,
        ) as response:

            return json.loads(
                response
                .read()
                .decode("utf-8")
            )

    # =====================================================
    # 获取 UTC+8 当日状态
    #
    # Futures 日线不是直接使用 UTC 00:00。
    #
    # 我们自己使用：
    #
    # UTC+8 00:00
    #
    # 作为 Market Radar 的 Crypto 日涨跌基准。
    # =====================================================

    def load_utc8_day_state(
        self,
        symbol: str,
    ):

        try:

            now_utc8 = (
                datetime.now(
                    UTC8
                )
            )

            midnight_utc8 = (
                now_utc8.replace(
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
            )

            start_time = int(
                midnight_utc8
                .timestamp()
                * 1000
            )

            params = {
                "symbol":
                    symbol.upper(),

                "interval":
                    "1m",

                "startTime":
                    start_time,

                "limit":
                    1500,
            }

            url = (
                f"{self.REST_BASE_URL}"
                f"/fapi/v1/klines?"
                f"{urlencode(params)}"
            )

            data = (
                self._read_json(
                    url
                )
            )

            if not data:

                print(
                    f"[FUTURES NO DATA] "
                    f"{symbol}"
                )

                return None

            day_open = float(
                data[0][1]
            )

            day_high = max(
                float(item[2])
                for item
                in data
            )

            day_low = min(
                float(item[3])
                for item
                in data
            )

            volume = sum(
                float(item[5])
                for item
                in data
            )

            quote_volume = sum(
                float(item[7])
                for item
                in data
            )

            return {
                "day_open":
                    day_open,

                "day_high":
                    day_high,

                "day_low":
                    day_low,

                "volume":
                    volume,

                "quote_volume":
                    quote_volume,

                "session_date":
                    now_utc8.date(),
            }

        except Exception as error:

            print(
                f"[FUTURES INIT ERROR] "
                f"{symbol}: {error}"
            )

            return None

    # =====================================================
    # Dynamic Futures WebSocket
    # =====================================================

    async def stream_markets_dynamic(
        self,
        symbol_loader,
        refresh_seconds: int = 5,
    ):

        request_id = 1

        while True:

            try:

                print()
                print(
                    "正在建立 Binance "
                    "Futures WebSocket..."
                )

                proxy_url = os.getenv(
                    "BINANCE_PROXY_URL"
                )

                if proxy_url:

                    print(
                        "Binance Futures "
                        "使用代理：",
                        proxy_url,
                    )

                    proxy = (
                        Proxy.from_url(
                            proxy_url
                        )
                    )

                    connection = (
                        proxy_connect(
                            self.BASE_URL,
                            proxy=proxy,
                            open_timeout=15,
                            ping_interval=20,
                            ping_timeout=20,
                            close_timeout=10,
                        )
                    )

                else:

                    print(
                        "Binance Futures "
                        "未设置代理，使用直连"
                    )

                    connection = (
                        websockets.connect(
                            self.BASE_URL,
                            open_timeout=15,
                            ping_interval=20,
                            ping_timeout=20,
                            close_timeout=10,
                        )
                    )

                async with (
                    connection
                    as websocket
                ):

                    print(
                        "Binance Futures "
                        "WebSocket 连接成功"
                    )

                    subscribed_symbols = (
                        set()
                    )

                    states = {}

                    last_refresh = 0.0

                    while True:

                        now_monotonic = (
                            time.monotonic()
                        )

                        # =================================
                        # 动态检查数据库
                        # =================================

                        if (
                            now_monotonic
                            - last_refresh
                            >= refresh_seconds
                        ):

                            desired_symbols = {
                                symbol.upper()

                                for symbol
                                in symbol_loader()
                            }

                            added_symbols = (
                                desired_symbols
                                - subscribed_symbols
                            )

                            removed_symbols = (
                                subscribed_symbols
                                - desired_symbols
                            )

                            # =============================
                            # SUBSCRIBE
                            # =============================

                            valid_added = set()

                            for symbol in (
                                sorted(
                                    added_symbols
                                )
                            ):

                                state = (
                                    await asyncio
                                    .to_thread(
                                        self
                                        .load_utc8_day_state,
                                        symbol,
                                    )
                                )

                                if state is None:

                                    print(
                                        "[FUTURES SKIP] "
                                        f"{symbol}"
                                    )

                                    continue

                                states[
                                    symbol
                                ] = state

                                valid_added.add(
                                    symbol
                                )

                            if valid_added:

                                message = {
                                    "method":
                                        "SUBSCRIBE",

                                    "params":
                                        self
                                        .build_streams(
                                            valid_added
                                        ),

                                    "id":
                                        request_id,
                                }

                                request_id += 1

                                await websocket.send(
                                    json.dumps(
                                        message
                                    )
                                )

                                subscribed_symbols.update(
                                    valid_added
                                )

                                print(
                                    "[FUTURES SUBSCRIBE] "
                                    + ", ".join(
                                        sorted(
                                            valid_added
                                        )
                                    )
                                )

                            # =============================
                            # UNSUBSCRIBE
                            # =============================

                            if removed_symbols:

                                message = {
                                    "method":
                                        "UNSUBSCRIBE",

                                    "params":
                                        self
                                        .build_streams(
                                            removed_symbols
                                        ),

                                    "id":
                                        request_id,
                                }

                                request_id += 1

                                await websocket.send(
                                    json.dumps(
                                        message
                                    )
                                )

                                for symbol in (
                                    removed_symbols
                                ):

                                    states.pop(
                                        symbol,
                                        None,
                                    )

                                subscribed_symbols\
                                    .difference_update(
                                        removed_symbols
                                    )

                                print(
                                    "[FUTURES UNSUBSCRIBE] "
                                    + ", ".join(
                                        sorted(
                                            removed_symbols
                                        )
                                    )
                                )

                            last_refresh = (
                                now_monotonic
                            )

                        # =================================
                        # 接收行情
                        # =================================

                        try:

                            raw_message = (
                                await asyncio
                                .wait_for(
                                    websocket.recv(),
                                    timeout=1.0,
                                )
                            )

                        except (
                            asyncio.TimeoutError
                        ):

                            continue

                        payload = json.loads(
                            raw_message
                        )

                        # SUBSCRIBE ACK

                        if (
                            "result" in payload
                            and
                            "id" in payload
                        ):

                            continue

                        data = payload.get(
                            "data",
                            payload,
                        )

                        if (
                            data.get("e")
                            != "trade"
                        ):

                            continue

                        symbol = (
                            data.get("s")
                        )

                        if not symbol:

                            continue

                        symbol = (
                            symbol.upper()
                        )

                        if (
                            symbol
                            not in
                            subscribed_symbols
                        ):

                            continue

                        state = states.get(
                            symbol
                        )

                        if state is None:

                            continue

                        # =================================
                        # UTC+8 换日
                        # =================================

                        current_date = (
                            datetime.now(
                                UTC8
                            ).date()
                        )

                        if (
                            state[
                                "session_date"
                            ]
                            != current_date
                        ):

                            new_state = (
                                await asyncio
                                .to_thread(
                                    self
                                    .load_utc8_day_state,
                                    symbol,
                                )
                            )

                            if (
                                new_state
                                is not None
                            ):

                                state = (
                                    new_state
                                )

                                states[
                                    symbol
                                ] = (
                                    new_state
                                )

                        # =================================
                        # Trade
                        # =================================

                        price = float(
                            data["p"]
                        )

                        # =================================
                        # Invalid Futures trade guard
                        #
                        # Binance trade price must be
                        # finite and greater than zero.
                        # =================================

                        if (
                            not math.isfinite(
                                price
                            )
                            or price <= 0
                        ):

                            print(
                                "[FUTURES INVALID PRICE] "
                                f"{symbol} | "
                                f"raw_price="
                                f"{data.get('p')!r}"
                            )

                            continue

                        quantity = float(
                            data.get(
                                "q",
                                0,
                            )
                        )

                        state[
                            "day_high"
                        ] = max(
                            state[
                                "day_high"
                            ],
                            price,
                        )

                        state[
                            "day_low"
                        ] = min(
                            state[
                                "day_low"
                            ],
                            price,
                        )

                        state[
                            "volume"
                        ] += quantity

                        state[
                            "quote_volume"
                        ] += (
                            price
                            * quantity
                        )

                        event_ms = (
                            data.get("T")
                            or
                            data.get("E")
                        )

                        event_time = (
                            datetime
                            .fromtimestamp(
                                event_ms
                                / 1000,
                                tz=timezone.utc,
                            )
                            .replace(
                                tzinfo=None
                            )
                        )

                        snapshot = (
                            self.build_snapshot(
                                symbol=symbol,
                                price=price,
                                day_open=state[
                                    "day_open"
                                ],
                                day_high=state[
                                    "day_high"
                                ],
                                day_low=state[
                                    "day_low"
                                ],
                                volume=state[
                                    "volume"
                                ],
                                quote_volume=state[
                                    "quote_volume"
                                ],
                                event_time=(
                                    event_time
                                ),
                                session_date=(
                                    state[
                                        "session_date"
                                    ]
                                ),
                            )
                        )

                        yield snapshot

            except asyncio.CancelledError:

                raise

            except Exception as error:

                print()
                print(
                    "[BINANCE FUTURES ERROR]"
                )

                print(
                    f"{type(error).__name__}: "
                    f"{error}"
                )

                print(
                    "5 秒后重新连接..."
                )

                print()

                await asyncio.sleep(
                    5
                )