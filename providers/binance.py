import asyncio
import json
import os
import time
from datetime import (
    datetime,
    timedelta,
    timezone,
)

import websockets

from websockets_proxy import (
    Proxy,
    proxy_connect,
)

from providers.base import (
    DailyBar,
    MarketSnapshot,
)

from urllib.parse import urlencode
from urllib.request import urlopen


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
    REST_BASE_URL = (
        "https://api.binance.com"
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

    def get_daily_history(
            self,
            symbol: str,
            start_date,
            end_date,
    ) -> list[DailyBar]:

        # =====================================================
        # Binance 日线必须继续使用 UTC+8
        #
        # 与实时行情定义保持一致
        # =====================================================

        start_datetime = datetime(
            start_date.year,
            start_date.month,
            start_date.day,
            tzinfo=UTC8,
        )

        end_datetime = datetime(
            end_date.year,
            end_date.month,
            end_date.day,
            23,
            59,
            59,
            999000,
            tzinfo=UTC8,
        )

        start_ms = int(
            start_datetime.timestamp()
            * 1000
        )

        end_ms = int(
            end_datetime.timestamp()
            * 1000
        )

        bars = []

        current_start = (
            start_ms
        )

        # =====================================================
        # Binance 每次最多返回 1000 根 Kline
        # 所以这里支持自动分页
        # =====================================================

        while (
                current_start
                <= end_ms
        ):

            params = {
                "symbol": (
                    symbol.upper()
                ),
                "interval": "1d",
                "timeZone": "8",
                "startTime": (
                    current_start
                ),
                "endTime": (
                    end_ms
                ),
                "limit": 1000,
            }

            url = (
                f"{self.REST_BASE_URL}"
                f"/api/v3/klines?"
                f"{urlencode(params)}"
            )

            with urlopen(
                    url,
                    timeout=15,
            ) as response:

                data = json.loads(
                    response.read()
                    .decode("utf-8")
                )

            if not data:
                break

            for item in data:

                open_time = (
                    int(item[0])
                )

                open_price = float(
                    item[1]
                )

                high_price = float(
                    item[2]
                )

                low_price = float(
                    item[3]
                )

                close_price = float(
                    item[4]
                )

                volume = float(
                    item[5]
                )

                session_date = (
                    datetime.fromtimestamp(
                        open_time / 1000,
                        tz=UTC8,
                    ).date()
                )

                if open_price:

                    change_pct = (
                            (
                                    close_price
                                    - open_price
                            )
                            / open_price
                            * 100
                    )

                else:

                    change_pct = None

                bars.append(
                    DailyBar(
                        date=session_date,
                        open=open_price,
                        high=high_price,
                        low=low_price,
                        close=close_price,
                        volume=volume,
                        change_pct=change_pct,
                    )
                )

            # 最后一根 Kline 的开盘时间
            last_open_time = int(
                data[-1][0]
            )

            next_start = (
                    last_open_time
                    + 1
            )

            if (
                    next_start
                    <= current_start
            ):
                break

            current_start = (
                next_start
            )

            if len(data) < 1000:
                break

        return bars

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

                proxy_url = os.getenv(
                    "BINANCE_PROXY_URL"
                )

                if proxy_url:

                    print(
                        "Binance 使用代理：",
                        proxy_url,
                    )

                    proxy = Proxy.from_url(
                        proxy_url
                    )

                    connection = proxy_connect(
                        self.BASE_URL,
                        proxy=proxy,
                        open_timeout=15,
                        ping_interval=20,
                        ping_timeout=20,
                        close_timeout=10,
                    )

                else:

                    print(
                        "Binance 未设置代理，使用直连"
                    )

                    connection = websockets.connect(
                        self.BASE_URL,
                        open_timeout=15,
                        ping_interval=20,
                        ping_timeout=20,
                        close_timeout=10,
                    )

                async with connection as websocket:

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

                import traceback

                print()

                print(

                    "Binance 动态 WebSocket 异常"

                )

                print(

                    "异常类型：",

                    type(error).__name__,

                )

                print(

                    "异常 repr：",

                    repr(error),

                )

                print(

                    "完整 traceback："

                )

                traceback.print_exc()

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