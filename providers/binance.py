import asyncio
import json
import time
from datetime import (
    datetime,
    timedelta,
    timezone,
)

import websockets

from providers.base import (
    MarketSnapshot,
)


UTC8 = timezone(
    timedelta(hours=8)
)


class BinanceSpotProvider:
    """
    Binance Spot Provider

    V0.9:
    - 单 WebSocket
    - 多 Symbol
    - 动态 SUBSCRIBE
    - 动态 UNSUBSCRIBE
    - UTC+8 日涨跌
    - 自动重连
    """

    BASE_URL = (
        "wss://stream.binance.com:9443/stream"
    )

    # =====================================================
    # MarketSnapshot
    # =====================================================

    @staticmethod
    def build_snapshot(
        symbol: str,
        price: float,
        day_open: float,
        day_high: float,
        day_low: float,
        volume: float,
        quote_volume: float,
        event_time: datetime,
        session_date,
    ) -> MarketSnapshot:

        change_amount = (
            price
            - day_open
        )

        if day_open == 0:

            change_pct = None

        else:

            change_pct = (
                change_amount
                / day_open
                * 100
            )

        return MarketSnapshot(

            symbol=(
                symbol.upper()
            ),

            asset_type="crypto",

            venue="BINANCE",

            price=price,

            reference_price=(
                day_open
            ),

            change_amount=(
                change_amount
            ),

            change_pct=(
                change_pct
            ),

            open=day_open,

            high=day_high,

            low=day_low,

            volume=volume,

            quote_volume=(
                quote_volume
            ),

            event_time=(
                event_time
            ),

            session_date=(
                session_date
            ),

            reference_type=(
                "utc8_day_open"
            ),

            reference_timezone=(
                "UTC+08:00"
            ),
        )

    # =====================================================
    # Symbol → Binance Stream
    # =====================================================

    @staticmethod
    def build_streams(
        symbols: set[str],
    ) -> list[str]:

        streams = []

        for symbol in sorted(
            symbols
        ):

            stream_symbol = (
                symbol.lower()
            )

            streams.append(
                f"{stream_symbol}@trade"
            )

            streams.append(
                f"{stream_symbol}"
                f"@kline_1d@+08:00"
            )

        return streams

    # =====================================================
    # 创建 Symbol State
    # =====================================================

    @staticmethod
    def create_state():

        return {
            "day_open": None,
            "day_high": None,
            "day_low": None,
            "volume": None,
            "quote_volume": None,
            "session_date": None,
        }

    # =====================================================
    # 动态 Market Stream
    #
    # symbol_loader:
    # 每次调用返回当前数据库中需要订阅的 symbol
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
                    "动态 WebSocket..."
                )

                async with websockets.connect(
                    self.BASE_URL,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                ) as websocket:

                    print(
                        "Binance 动态 WebSocket "
                        "连接成功"
                    )

                    # =====================================
                    # 当前已经订阅的 Symbol
                    # =====================================

                    subscribed_symbols = set()

                    # =====================================
                    # 每个币自己的 UTC+8 日线状态
                    # =====================================

                    states = {}

                    last_refresh = 0.0

                    # =====================================
                    # WebSocket 主循环
                    # =====================================

                    while True:

                        now_monotonic = (
                            time.monotonic()
                        )

                        # =================================
                        # 每隔 N 秒检查一次数据库
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

                            # -----------------------------
                            # 新增 Symbol
                            # -----------------------------

                            added_symbols = (
                                desired_symbols
                                - subscribed_symbols
                            )

                            # -----------------------------
                            # 删除 Symbol
                            # -----------------------------

                            removed_symbols = (
                                subscribed_symbols
                                - desired_symbols
                            )

                            # =============================
                            # SUBSCRIBE
                            # =============================

                            if added_symbols:

                                streams = (
                                    self.build_streams(
                                        added_symbols
                                    )
                                )

                                message = {
                                    "method": (
                                        "SUBSCRIBE"
                                    ),

                                    "params": (
                                        streams
                                    ),

                                    "id": (
                                        request_id
                                    ),
                                }

                                request_id += 1

                                await websocket.send(
                                    json.dumps(
                                        message
                                    )
                                )

                                for symbol in (
                                    added_symbols
                                ):

                                    states[
                                        symbol
                                    ] = (
                                        self
                                        .create_state()
                                    )

                                subscribed_symbols.update(
                                    added_symbols
                                )

                                print(
                                    "[SUBSCRIBE] "
                                    + ", ".join(
                                        sorted(
                                            added_symbols
                                        )
                                    )
                                )

                            # =============================
                            # UNSUBSCRIBE
                            # =============================

                            if removed_symbols:

                                streams = (
                                    self.build_streams(
                                        removed_symbols
                                    )
                                )

                                message = {
                                    "method": (
                                        "UNSUBSCRIBE"
                                    ),

                                    "params": (
                                        streams
                                    ),

                                    "id": (
                                        request_id
                                    ),
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

                                subscribed_symbols.difference_update(
                                    removed_symbols
                                )

                                print(
                                    "[UNSUBSCRIBE] "
                                    + ", ".join(
                                        sorted(
                                            removed_symbols
                                        )
                                    )
                                )

                            # =============================
                            # 状态输出
                            # =============================

                            if (
                                added_symbols
                                or removed_symbols
                            ):

                                print(
                                    "当前订阅："
                                    + (
                                        ", ".join(
                                            sorted(
                                                subscribed_symbols
                                            )
                                        )
                                        if subscribed_symbols
                                        else "无"
                                    )
                                )

                                print(
                                    f"Symbol 数："
                                    f"{len(
                                        subscribed_symbols
                                    )}"
                                )

                                print(
                                    f"Stream 数："
                                    f"{len(
                                        subscribed_symbols
                                    ) * 2}"
                                )

                                print(
                                    "Crypto 涨跌基准："
                                    "UTC+8 00:00"
                                )

                                print()

                            last_refresh = (
                                now_monotonic
                            )

                        # =================================
                        # 接收 WebSocket
                        #
                        # timeout 是为了让数据库检查
                        # 不会被 websocket.recv 永久卡住
                        # =================================

                        try:

                            raw_message = (
                                await asyncio.wait_for(
                                    websocket.recv(),
                                    timeout=1.0,
                                )
                            )

                        except asyncio.TimeoutError:

                            continue

                        payload = (
                            json.loads(
                                raw_message
                            )
                        )

                        # =================================
                        # SUBSCRIBE / UNSUBSCRIBE ACK
                        # =================================

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

                        event_type = (
                            data.get("e")
                        )

                        symbol = (
                            data.get("s")
                        )

                        if not symbol:

                            continue

                        symbol = (
                            symbol.upper()
                        )

                        # =================================
                        # 可能是 UNSUBSCRIBE 途中
                        # 残留的最后几条消息
                        # =================================

                        if (
                            symbol
                            not in subscribed_symbols
                        ):

                            continue

                        state = (
                            states.get(
                                symbol
                            )
                        )

                        if state is None:

                            continue

                        # =================================
                        # UTC+8 KLINE
                        # =================================

                        if (
                            event_type
                            == "kline"
                        ):

                            kline = (
                                data["k"]
                            )

                            state[
                                "day_open"
                            ] = float(
                                kline["o"]
                            )

                            state[
                                "day_high"
                            ] = float(
                                kline["h"]
                            )

                            state[
                                "day_low"
                            ] = float(
                                kline["l"]
                            )

                            state[
                                "volume"
                            ] = float(
                                kline["v"]
                            )

                            state[
                                "quote_volume"
                            ] = float(
                                kline["q"]
                            )

                            current_price = float(
                                kline["c"]
                            )

                            event_time = (
                                datetime
                                .fromtimestamp(
                                    data["E"]
                                    / 1000,

                                    tz=(
                                        timezone.utc
                                    ),
                                )
                            )

                            kline_start = (
                                datetime
                                .fromtimestamp(
                                    kline["t"]
                                    / 1000,

                                    tz=(
                                        timezone.utc
                                    ),
                                )
                            )

                            state[
                                "session_date"
                            ] = (
                                kline_start
                                .astimezone(
                                    UTC8
                                )
                                .date()
                            )

                            yield (
                                self.build_snapshot(

                                    symbol=symbol,

                                    price=(
                                        current_price
                                    ),

                                    day_open=(
                                        state[
                                            "day_open"
                                        ]
                                    ),

                                    day_high=(
                                        state[
                                            "day_high"
                                        ]
                                    ),

                                    day_low=(
                                        state[
                                            "day_low"
                                        ]
                                    ),

                                    volume=(
                                        state[
                                            "volume"
                                        ]
                                    ),

                                    quote_volume=(
                                        state[
                                            "quote_volume"
                                        ]
                                    ),

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

                            continue

                        # =================================
                        # TRADE
                        # =================================

                        if (
                            event_type
                            == "trade"
                        ):

                            current_price = float(
                                data["p"]
                            )

                            event_time = (
                                datetime
                                .fromtimestamp(
                                    data["T"]
                                    / 1000,

                                    tz=(
                                        timezone.utc
                                    ),
                                )
                            )

                            trade_date = (
                                event_time
                                .astimezone(
                                    UTC8
                                )
                                .date()
                            )

                            # -----------------------------
                            # 尚未获得当前 UTC+8 日 K
                            # -----------------------------

                            if (
                                state[
                                    "day_open"
                                ]
                                is None
                                or
                                state[
                                    "session_date"
                                ]
                                is None
                            ):

                                continue

                            # -----------------------------
                            # UTC+8 跨日保护
                            # -----------------------------

                            if (
                                trade_date
                                != state[
                                    "session_date"
                                ]
                            ):

                                continue

                            # -----------------------------
                            # High
                            # -----------------------------

                            if (
                                state[
                                    "day_high"
                                ]
                                is None
                            ):

                                state[
                                    "day_high"
                                ] = (
                                    current_price
                                )

                            else:

                                state[
                                    "day_high"
                                ] = max(
                                    state[
                                        "day_high"
                                    ],
                                    current_price,
                                )

                            # -----------------------------
                            # Low
                            # -----------------------------

                            if (
                                state[
                                    "day_low"
                                ]
                                is None
                            ):

                                state[
                                    "day_low"
                                ] = (
                                    current_price
                                )

                            else:

                                state[
                                    "day_low"
                                ] = min(
                                    state[
                                        "day_low"
                                    ],
                                    current_price,
                                )

                            yield (
                                self.build_snapshot(

                                    symbol=symbol,

                                    price=(
                                        current_price
                                    ),

                                    day_open=(
                                        state[
                                            "day_open"
                                        ]
                                    ),

                                    day_high=(
                                        state[
                                            "day_high"
                                        ]
                                    ),

                                    day_low=(
                                        state[
                                            "day_low"
                                        ]
                                    ),

                                    volume=(
                                        state[
                                            "volume"
                                        ]
                                    ),

                                    quote_volume=(
                                        state[
                                            "quote_volume"
                                        ]
                                    ),

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

            except asyncio.CancelledError:

                raise

            except Exception as error:

                print(
                    "Binance 动态 WebSocket "
                    f"异常：{error}"
                )

                print(
                    "3 秒后自动重新连接..."
                )

                await asyncio.sleep(
                    3
                )

    # =====================================================
    # V0.8 兼容接口
    # =====================================================

    async def stream_markets(
        self,
        symbols: list[str],
    ):

        fixed_symbols = [
            symbol.upper()
            for symbol in symbols
        ]

        def loader():

            return fixed_symbols

        async for snapshot in (
            self.stream_markets_dynamic(
                symbol_loader=loader,
                refresh_seconds=3600,
            )
        ):

            yield snapshot

    # =====================================================
    # V0.5 单币兼容接口
    # =====================================================

    async def stream_market(
        self,
        symbol: str,
    ):

        async for snapshot in (
            self.stream_markets(
                [
                    symbol
                ]
            )
        ):

            yield snapshot