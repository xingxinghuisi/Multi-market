import asyncio
import json
import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import websockets
from dotenv import load_dotenv

from providers.base import MarketSnapshot


load_dotenv()

KST = ZoneInfo(
    "Asia/Seoul"
)


class InfowayKoreaProvider:

    provider_name = "INFOWAY"

    WS_BASE_URL = (
        "wss://data.infoway.io/ws"
    )

    REQ_TRADE = 10000
    PUSH_TRADE = 10002

    REQ_KLINE = 10006
    PUSH_KLINE = 10008

    REQ_HEARTBEAT = 10010

    def __init__(self):

        self.api_key = os.getenv(
            "INFOWAY_API_KEY"
        )

        if not self.api_key:

            raise RuntimeError(
                "INFOWAY_API_KEY "
                "not found"
            )

    @staticmethod
    def _trace():

        return str(
            uuid.uuid4()
        )

    @staticmethod
    def _infoway_symbol(
        symbol: str,
    ):

        symbol = (
            symbol
            .strip()
            .upper()
        )

        if symbol.endswith(
            ".KS"
        ):

            return symbol

        return (
            f"{symbol}.KS"
        )

    @staticmethod
    def _local_symbol(
        symbol: str,
    ):

        symbol = (
            symbol
            .strip()
            .upper()
        )

        if symbol.endswith(
            ".KS"
        ):

            return symbol[:-3]

        return symbol

    @staticmethod
    def _to_float(
        value,
    ):

        if value is None:
            return None

        try:

            return float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):

            return None

    @staticmethod
    def _message_items(
        data,
    ):

        if data is None:

            return []

        if isinstance(
            data,
            list,
        ):

            return data

        if isinstance(
            data,
            dict,
        ):

            return [
                data
            ]

        return []

    @staticmethod
    def _create_state():

        return {
            "price": None,

            "previous_close": None,

            "open": None,
            "high": None,
            "low": None,

            "volume": None,
            "quote_volume": None,

            "change_amount": None,
            "change_pct": None,

            "session_date": None,
        }

    async def _heartbeat(
        self,
        websocket,
    ):

        while True:

            await asyncio.sleep(
                30
            )

            await websocket.send(
                json.dumps(
                    {
                        "code":
                            self.REQ_HEARTBEAT,

                        "trace":
                            self._trace(),
                    }
                )
            )

    async def _subscribe(
        self,
        websocket,
        symbols,
    ):

        codes = ",".join(
            self._infoway_symbol(
                symbol
            )
            for symbol
            in symbols
        )

        # =============================================
        # 实时逐笔成交
        # =============================================

        await websocket.send(
            json.dumps(
                {
                    "code":
                        self.REQ_TRADE,

                    "trace":
                        self._trace(),

                    "data": {
                        "codes":
                            codes
                    },
                }
            )
        )

        # =============================================
        # 日 K
        #
        # type = 8
        # =============================================

        await websocket.send(
            json.dumps(
                {
                    "code":
                        self.REQ_KLINE,

                    "trace":
                        self._trace(),

                    "data": {
                        "arr": [
                            {
                                "type": 8,
                                "codes": codes,
                            }
                        ]
                    },
                }
            )
        )

        print(
            "[INFOWAY SUBSCRIBE] "
            f"{codes}"
        )

    def _build_snapshot(
        self,
        symbol: str,
        state,
        event_time,
    ):

        price = state[
            "price"
        ]

        previous_close = state[
            "previous_close"
        ]

        if (
            price is None
            or previous_close is None
        ):

            return None

        change_amount = (
            price
            - previous_close
        )

        if previous_close:

            change_pct = (
                change_amount
                / previous_close
                * 100
            )

        else:

            change_pct = None

        return MarketSnapshot(

            symbol=symbol,

            asset_type="stock",

            venue="KRX",

            price=price,

            reference_price=(
                previous_close
            ),

            change_amount=(
                change_amount
            ),

            change_pct=(
                change_pct
            ),

            open=state[
                "open"
            ],

            high=state[
                "high"
            ],

            low=state[
                "low"
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

            reference_type=(
                "previous_close"
            ),

            reference_timezone=(
                "Asia/Seoul"
            ),
        )

    async def stream_markets(
        self,
        symbols,
    ):

        symbols = {
            symbol.upper()
            for symbol
            in symbols
        }

        states = {
            symbol:
                self._create_state()

            for symbol
            in symbols
        }

        ws_url = (
            f"{self.WS_BASE_URL}"
            f"?business=korea"
            f"&apikey={self.api_key}"
        )

        while True:

            heartbeat_task = None

            try:

                print()
                print(
                    "正在连接 Infoway "
                    "Korea WebSocket..."
                )

                async with websockets.connect(
                    ws_url,
                    ping_interval=None,
                    close_timeout=10,
                ) as websocket:

                    print(
                        "Infoway Korea "
                        "WebSocket 连接成功"
                    )

                    await self._subscribe(
                        websocket,
                        symbols,
                    )

                    heartbeat_task = (
                        asyncio.create_task(
                            self._heartbeat(
                                websocket
                            )
                        )
                    )

                    async for raw in websocket:

                        message = json.loads(
                            raw
                        )

                        code = message.get(
                            "code"
                        )

                        # =================================
                        # 连接成功 / 订阅 ACK
                        # =================================

                        if code in {
                            200,
                            10001,
                            10007,
                            10010,
                        }:

                            continue

                        data = message.get(
                            "data"
                        )

                        # =================================
                        # 日 K
                        #
                        # 用来初始化：
                        # open / high / low
                        # volume
                        # previous close
                        # =================================

                        if (
                            code
                            == self.PUSH_KLINE
                        ):

                            for item in (
                                self._message_items(
                                    data
                                )
                            ):

                                raw_symbol = (
                                    item.get(
                                        "s"
                                    )
                                )

                                if not raw_symbol:

                                    continue

                                symbol = (
                                    self._local_symbol(
                                        raw_symbol
                                    )
                                )

                                if symbol not in states:

                                    continue

                                state = states[
                                    symbol
                                ]

                                price = (
                                    self._to_float(
                                        item.get(
                                            "c"
                                        )
                                    )
                                )

                                open_price = (
                                    self._to_float(
                                        item.get(
                                            "o"
                                        )
                                    )
                                )

                                high_price = (
                                    self._to_float(
                                        item.get(
                                            "h"
                                        )
                                    )
                                )

                                low_price = (
                                    self._to_float(
                                        item.get(
                                            "l"
                                        )
                                    )
                                )

                                volume = (
                                    self._to_float(
                                        item.get(
                                            "v"
                                        )
                                    )
                                )

                                quote_volume = (
                                    self._to_float(
                                        item.get(
                                            "vw"
                                        )
                                    )
                                )

                                change_amount = (
                                    self._to_float(
                                        item.get(
                                            "pca"
                                        )
                                    )
                                )

                                if (
                                    price is None
                                ):

                                    continue

                                previous_close = None

                                if (
                                    change_amount
                                    is not None
                                ):

                                    previous_close = (
                                        price
                                        - change_amount
                                    )

                                state[
                                    "price"
                                ] = price

                                state[
                                    "previous_close"
                                ] = (
                                    previous_close
                                )

                                state[
                                    "open"
                                ] = open_price

                                state[
                                    "high"
                                ] = high_price

                                state[
                                    "low"
                                ] = low_price

                                state[
                                    "volume"
                                ] = volume

                                state[
                                    "quote_volume"
                                ] = quote_volume

                                state[
                                    "change_amount"
                                ] = change_amount

                                state[
                                    "session_date"
                                ] = (
                                    datetime.now(
                                        KST
                                    )
                                    .date()
                                    .isoformat()
                                )

                                event_time = (
                                    datetime.now(
                                        KST
                                    )
                                )

                                snapshot = (
                                    self._build_snapshot(
                                        symbol,
                                        state,
                                        event_time,
                                    )
                                )

                                if (
                                    snapshot
                                    is not None
                                ):

                                    yield snapshot

                        # =================================
                        # 实时逐笔成交
                        #
                        # Kline 初始化以后，
                        # 每笔成交都会更新实时价格
                        # =================================

                        elif (
                            code
                            == self.PUSH_TRADE
                        ):

                            for item in (
                                self._message_items(
                                    data
                                )
                            ):

                                raw_symbol = (
                                    item.get(
                                        "s"
                                    )
                                )

                                if not raw_symbol:

                                    continue

                                symbol = (
                                    self._local_symbol(
                                        raw_symbol
                                    )
                                )

                                if symbol not in states:

                                    continue

                                state = states[
                                    symbol
                                ]

                                price = (
                                    self._to_float(
                                        item.get(
                                            "p"
                                        )
                                    )
                                )

                                if price is None:

                                    continue

                                # Kline 还没有初始化
                                if (
                                    state[
                                        "previous_close"
                                    ]
                                    is None
                                ):

                                    continue

                                state[
                                    "price"
                                ] = price

                                if (
                                    state["high"]
                                    is None
                                    or price
                                    > state["high"]
                                ):

                                    state[
                                        "high"
                                    ] = price

                                if (
                                    state["low"]
                                    is None
                                    or price
                                    < state["low"]
                                ):

                                    state[
                                        "low"
                                    ] = price

                                event_time = (
                                    datetime.now(
                                        KST
                                    )
                                )

                                snapshot = (
                                    self._build_snapshot(
                                        symbol,
                                        state,
                                        event_time,
                                    )
                                )

                                if (
                                    snapshot
                                    is not None
                                ):

                                    yield snapshot

            except asyncio.CancelledError:

                raise

            except Exception as error:

                print()
                print(
                    "[INFOWAY ERROR]"
                )

                print(
                    f"{error}"
                )

                print(
                    "5 秒后重新连接..."
                )

                await asyncio.sleep(
                    5
                )

            finally:

                if (
                    heartbeat_task
                    is not None
                ):

                    heartbeat_task.cancel()