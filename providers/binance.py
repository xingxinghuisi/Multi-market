import asyncio
import json
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

    支持：
    - 单 symbol
    - 多 symbol 批量订阅

    Crypto 今日涨跌统一：
    UTC+8 00:00 → 当前价格
    """

    BASE_URL = (
        "wss://stream.binance.com:9443/stream"
    )

    # =====================================================
    # Snapshot
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
    # 批量实时行情
    # =====================================================

    async def stream_markets(
        self,
        symbols: list[str],
    ):

        symbols = [
            symbol.upper()
            for symbol in symbols
        ]

        if not symbols:

            return

        # =================================================
        # 每个 symbol 独立保存日线状态
        # =================================================

        states = {

            symbol: {
                "day_open": None,
                "day_high": None,
                "day_low": None,
                "volume": None,
                "quote_volume": None,
                "session_date": None,
            }

            for symbol
            in symbols
        }

        while True:

            try:

                print()
                print(
                    "正在建立 Binance "
                    "批量 WebSocket..."
                )

                print(
                    "订阅资产："
                    + ", ".join(
                        symbols
                    )
                )

                # =========================================
                # 每次重新连接
                # 清空旧日线状态
                # =========================================

                for state in (
                    states.values()
                ):

                    state[
                        "day_open"
                    ] = None

                    state[
                        "day_high"
                    ] = None

                    state[
                        "day_low"
                    ] = None

                    state[
                        "volume"
                    ] = None

                    state[
                        "quote_volume"
                    ] = None

                    state[
                        "session_date"
                    ] = None

                async with websockets.connect(
                    self.BASE_URL,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                ) as websocket:

                    # =====================================
                    # 生成批量订阅列表
                    #
                    # 每个 symbol 两个 stream：
                    #
                    # trade
                    # kline_1d@+08:00
                    # =====================================

                    streams = []

                    for symbol in symbols:

                        stream_symbol = (
                            symbol.lower()
                        )

                        streams.append(
                            f"{stream_symbol}"
                            f"@trade"
                        )

                        streams.append(
                            f"{stream_symbol}"
                            f"@kline_1d@+08:00"
                        )

                    subscribe_message = {

                        "method": "SUBSCRIBE",

                        "params": streams,

                        "id": "market-radar-batch",
                    }

                    await websocket.send(
                        json.dumps(
                            subscribe_message
                        )
                    )

                    print(
                        "Binance 批量 WebSocket "
                        "连接成功"
                    )

                    print(
                        f"订阅 Symbol 数："
                        f"{len(symbols)}"
                    )

                    print(
                        f"订阅 Stream 数："
                        f"{len(streams)}"
                    )

                    print(
                        "Crypto 涨跌基准："
                        "UTC+8 00:00"
                    )

                    print()

                    # =====================================
                    # 接收消息
                    # =====================================

                    async for message in websocket:

                        payload = json.loads(
                            message
                        )

                        # SUBSCRIBE 确认
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

                        if (
                            symbol
                            not in states
                        ):

                            continue

                        state = (
                            states[symbol]
                        )

                        # =================================
                        # UTC+8 日 K
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
                                datetime.fromtimestamp(
                                    data["E"] / 1000,
                                    tz=timezone.utc,
                                )
                            )

                            kline_start = (
                                datetime.fromtimestamp(
                                    kline["t"] / 1000,
                                    tz=timezone.utc,
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

                            snapshot = (
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

                            yield snapshot

                            continue

                        # =================================
                        # Trade
                        # =================================

                        if (
                            event_type
                            == "trade"
                        ):

                            current_price = float(
                                data["p"]
                            )

                            event_time = (
                                datetime.fromtimestamp(
                                    data["T"] / 1000,
                                    tz=timezone.utc,
                                )
                            )

                            trade_date = (
                                event_time
                                .astimezone(
                                    UTC8
                                )
                                .date()
                            )

                            # --------------------------------
                            # 还没收到日 K
                            # --------------------------------

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

                            # --------------------------------
                            # 刚跨 UTC+8 00:00
                            # 等新日 K 到来
                            # --------------------------------

                            if (
                                trade_date
                                != state[
                                    "session_date"
                                ]
                            ):

                                continue

                            # --------------------------------
                            # 更新 high
                            # --------------------------------

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

                            # --------------------------------
                            # 更新 low
                            # --------------------------------

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

                            snapshot = (
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

                            yield snapshot

            except asyncio.CancelledError:

                raise

            except Exception as error:

                print(
                    f"Binance 批量连接异常："
                    f"{error}"
                )

                print(
                    "3 秒后重新连接..."
                )

                await asyncio.sleep(
                    3
                )

    # =====================================================
    # 单 Symbol 兼容接口
    #
    # V0.5 的测试文件继续可以使用
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