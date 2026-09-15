import asyncio
import math
from datetime import (
    datetime,
    timezone,
)
from zoneinfo import ZoneInfo

from moomoo import (
    OpenQuoteContext,
    RET_OK,
    StockQuoteHandlerBase,
    SubType,
)

from providers.base import MarketSnapshot


# =========================================================
# Moomoo Quote Callback Handler
# =========================================================

class _MoomooQuoteHandler(
    StockQuoteHandlerBase
):

    def __init__(
        self,
        loop,
        queue,
        provider,
    ):

        super().__init__()

        self.loop = loop
        self.queue = queue
        self.provider = provider

    def _enqueue(
        self,
        snapshot,
    ):

        # 高频行情时，避免队列无限堆积
        if self.queue.full():

            try:
                self.queue.get_nowait()

            except asyncio.QueueEmpty:
                pass

        self.queue.put_nowait(
            snapshot
        )

    def on_recv_rsp(
        self,
        rsp_pb,
    ):

        ret_code, data = (
            super().on_recv_rsp(
                rsp_pb
            )
        )

        if ret_code != RET_OK:

            print(
                "[MOOMOO QUOTE ERROR]",
                data,
            )

            return (
                ret_code,
                data,
            )

        for _, row in data.iterrows():

            snapshot = (
                self.provider
                .row_to_snapshot(
                    row
                )
            )

            if snapshot is None:
                continue

            self.loop.call_soon_threadsafe(
                self._enqueue,
                snapshot,
            )

        return (
            RET_OK,
            data,
        )


# =========================================================
# Moomoo Realtime Provider
# =========================================================

class MoomooRealtimeProvider:

    provider_name = "MOOMOO"

    HOST = "127.0.0.1"
    PORT = 11111

    MARKET_META = {

        "US": {
            "venue": "US",
            "timezone": "America/New_York",
        },

        "HK": {
            "venue": "HKEX",
            "timezone": "Asia/Hong_Kong",
        },
    }

    def __init__(
        self,
        host=None,
        port=None,
    ):

        self.host = (
            host
            or self.HOST
        )

        self.port = (
            port
            or self.PORT
        )

        # 当前有效价格缓存
        #
        # 用于交易时段切换时，
        # 新时段暂时还没有第一笔价格的情况。
        self._last_active_prices = {}

        # Moomoo 返回的真实市场状态
        #
        # US.NVDA -> OVERNIGHT
        # US.AAPL -> AFTER_HOURS_BEGIN
        self._market_states = {}

        # 各交易阶段最后一次观察到价格变化的时间
        self._session_price_state = {}

    # =====================================================
    # 通用工具
    # =====================================================

    @staticmethod
    def _to_float(
        value,
    ):

        if value is None:
            return None

        try:

            result = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):

            return None

        if not math.isfinite(
            result
        ):

            return None

        return result

    @staticmethod
    def _is_valid_price(
        value,
    ):

        return (
            value is not None
            and value > 0
        )

    @staticmethod
    def _parse_code(
        code,
    ):

        text = (
            str(code)
            .strip()
            .upper()
        )

        if "." not in text:
            return None, None

        market, symbol = (
            text.split(
                ".",
                1,
            )
        )

        return (
            market,
            symbol,
        )

    @staticmethod
    def _parse_event_time(
        value,
        timezone_name,
    ):

        timezone = ZoneInfo(
            timezone_name
        )

        if value:

            try:

                dt = datetime.fromisoformat(
                    str(value)
                )

                if dt.tzinfo is None:

                    dt = dt.replace(
                        tzinfo=timezone
                    )

                return dt

            except ValueError:
                pass

        return datetime.now(
            timezone
        )

    # =====================================================
    # US Session
    #
    # 美东时间：
    #
    # 04:00 - 09:30  pre
    # 09:30 - 16:00  regular
    # 16:00 - 20:00  after
    # 20:00 - 04:00  overnight
    #
    # 周末增加 closed 判断。
    # =====================================================


    @staticmethod
    def _map_moomoo_market_state(
        state,
    ):

        if not state:
            return None

        state = (
            str(state)
            .strip()
            .upper()
        )

        if state == "PRE_MARKET_BEGIN":
            return "pre"

        if state == "AFTERNOON":
            return "regular"

        if state == "AFTER_HOURS_BEGIN":
            return "after"

        if state == "OVERNIGHT":
            return "overnight"

        if state in {
            "NONE",
            "CLOSED",
            "PRE_MARKET_END",
            "AFTER_HOURS_END",
        }:
            return "closed"

        return None

    @staticmethod
    def _get_us_session():

        now = datetime.now(
            ZoneInfo(
                "America/New_York"
            )
        )

        weekday = (
            now.weekday()
        )

        minutes = (
            now.hour * 60
            + now.minute
        )

        # Saturday
        if weekday == 5:
            return "closed"

        # Sunday
        #
        # 20:00 后进入下一交易日夜盘
        if weekday == 6:

            if minutes >= 1200:
                return "overnight"

            return "closed"

        # Friday 20:00 后
        if (
            weekday == 4
            and minutes >= 1200
        ):

            return "closed"

        # 04:00 - 09:30
        if (
            240
            <= minutes
            < 570
        ):

            return "pre"

        # 09:30 - 16:00
        if (
            570
            <= minutes
            < 960
        ):

            return "regular"

        # 16:00 - 20:00
        if (
            960
            <= minutes
            < 1200
        ):

            return "after"

        # 20:00 - 04:00
        return "overnight"

    def _select_us_price(
        self,
        code,
        regular_price,
        pre_price,
        after_price,
        overnight_price,
    ):

        # 优先使用 Moomoo 对该标的返回的真实状态。
        #
        # 如果暂时没有取得状态，
        # 才退回美东时间判断。
        session = (
                self._market_states.get(
                    code
                )
                or self._get_us_session()
        )

        # =============================================
        # 当前 session 的优先价格
        # =============================================

        if session == "pre":

            candidates = [
                pre_price,
                overnight_price,
                regular_price,
            ]

        elif session == "regular":

            candidates = [
                regular_price,
                pre_price,
                overnight_price,
            ]

        elif session == "after":

            candidates = [
                after_price,
                regular_price,
            ]

        elif session == "overnight":

            candidates = [
                overnight_price,
                after_price,
                regular_price,
            ]

        else:

            # 市场关闭时：
            #
            # 优先保持程序运行期间记录的
            # 最后一笔有效价格。
            candidates = [
                self._last_active_prices.get(
                    code
                ),
                after_price,
                overnight_price,
                regular_price,
                pre_price,
            ]

        price = None

        for candidate in candidates:

            if self._is_valid_price(
                candidate
            ):

                price = candidate
                break

        # =============================================
        # 缓存最后有效价格
        # =============================================

        if self._is_valid_price(
            price
        ):

            self._last_active_prices[
                code
            ] = price

        return (
            price,
            session,
        )

    # =====================================================
    # Moomoo Row -> MarketSnapshot
    # =====================================================

    def row_to_snapshot(
        self,
        row,
    ):

        raw_code = (
            row.get(
                "code"
            )
        )

        market, symbol = (
            self._parse_code(
                raw_code
            )
        )

        if (
            market is None
            or symbol is None
        ):

            return None

        meta = (
            self.MARKET_META.get(
                market
            )
        )

        if meta is None:
            return None

        code = (
            str(raw_code)
            .strip()
            .upper()
        )

        # =============================================
        # 四套美股价格
        #
        # last_price:
        # 正常盘 / 收盘价格
        #
        # pre_price:
        # 盘前价格
        #
        # after_price:
        # 盘后价格
        #
        # overnight_price:
        # 夜盘价格
        # =============================================

        regular_price = (
            self._to_float(
                row.get(
                    "last_price"
                )
            )
        )

        pre_price = (
            self._to_float(
                row.get(
                    "pre_price"
                )
            )
        )

        after_price = (
            self._to_float(
                row.get(
                    "after_price"
                )
            )
        )

        overnight_price = (
            self._to_float(
                row.get(
                    "overnight_price"
                )
            )
        )

        # =============================================
        # 记录各阶段价格最后变化时间
        #
        # 这里记录的是 Market Radar 实际观察到
        # Moomoo 字段发生变化的时间。
        # =============================================

        observed_at = datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

        session_state = (
            self._session_price_state
            .setdefault(
                code,
                {}
            )
        )

        def update_session_time(
                key,
                value,
        ):

            if not self._is_valid_price(
                    value
            ):
                return

            value_key = (
                f"{key}_value"
            )

            updated_key = (
                f"{key}_updated_at"
            )

            previous_value = (
                session_state.get(
                    value_key
                )
            )

            # 第一次看到这个阶段价格：
            # 只保存价格基准，不伪造更新时间。
            if previous_value is None:
                session_state[
                    value_key
                ] = value

                return

            # 只有价格真正变化，
            # 才更新时间。
            if value != previous_value:
                session_state[
                    value_key
                ] = value

                session_state[
                    updated_key
                ] = observed_at

        update_session_time(
            "regular",
            regular_price,
        )

        update_session_time(
            "pre",
            pre_price,
        )

        update_session_time(
            "after",
            after_price,
        )

        update_session_time(
            "overnight",
            overnight_price,
        )

        # =============================================
        # 当前显示价格
        # =============================================

        if market == "US":

            price, market_session = (
                self._select_us_price(
                    code=code,

                    regular_price=(
                        regular_price
                    ),

                    pre_price=(
                        pre_price
                    ),

                    after_price=(
                        after_price
                    ),

                    overnight_price=(
                        overnight_price
                    ),
                )
            )

        else:

            # 港股暂时使用正常 last_price
            price = regular_price
            market_session = "regular"

        if price is None:
            return None

        # =============================================
        # Previous Close
        # =============================================

        previous_close = (
            self._to_float(
                row.get(
                    "prev_close_price"
                )
            )
        )

        # =============================================
        # Change
        #
        # 当前价格相对于昨收
        # =============================================

        change_amount = None
        change_pct = None

        if previous_close is not None:

            change_amount = (
                price
                - previous_close
            )

            if previous_close != 0:

                change_pct = (
                    change_amount
                    / previous_close
                    * 100
                )

        # =============================================
        # Event Time
        # =============================================

        event_time = (
            self._parse_event_time(
                row.get(
                    "update_time"
                ),
                meta[
                    "timezone"
                ],
            )
        )

        # =============================================
        # MarketSnapshot
        # =============================================

        return MarketSnapshot(

            symbol=symbol,

            asset_type="stock",

            venue=meta[
                "venue"
            ],

            # 当前活跃交易阶段价格
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

            open=self._to_float(
                row.get(
                    "open_price"
                )
            ),

            high=self._to_float(
                row.get(
                    "high_price"
                )
            ),

            low=self._to_float(
                row.get(
                    "low_price"
                )
            ),

            volume=self._to_float(
                row.get(
                    "volume"
                )
            ),

            quote_volume=self._to_float(
                row.get(
                    "turnover"
                )
            ),

            event_time=event_time,

            session_date=(
                event_time
                .date()
                .isoformat()
            ),

            reference_type=(
                "previous_close"
            ),

            reference_timezone=(
                meta[
                    "timezone"
                ]
            ),

            # =========================================
            # US Extended Session Prices
            # =========================================

            regular_price=(
                regular_price
            ),

            pre_price=(
                pre_price
            ),

            after_price=(
                after_price
            ),

            overnight_price=(
                overnight_price
            ),

            market_session=(
                market_session
            ),

            regular_updated_at=(
                session_state.get(
                    "regular_updated_at"
                )
            ),

            pre_updated_at=(
                session_state.get(
                    "pre_updated_at"
                )
            ),

            after_updated_at=(
                session_state.get(
                    "after_updated_at"
                )
            ),

            overnight_updated_at=(
                session_state.get(
                    "overnight_updated_at"
                )
            ),
        )



    # =====================================================
    # Codes
    # =====================================================

    @staticmethod
    def _normalize_codes(
        codes,
    ):

        return {

            str(code)
            .strip()
            .upper()

            for code
            in codes

            if str(code).strip()
        }

    # =====================================================
    # Subscribe
    # =====================================================

    async def _subscribe_code(
        self,
        quote_ctx,
        code,
    ):

        ret, data = (
            await asyncio.to_thread(
                quote_ctx.subscribe,

                [code],

                [
                    SubType.QUOTE
                ],

                subscribe_push=True,
            )
        )

        if ret != RET_OK:

            print(
                "[MOOMOO SUBSCRIBE ERROR] "
                f"{code} | {data}"
            )

            return False

        print(
            "[MOOMOO SUBSCRIBE] "
            f"{code}"
        )

        return True

    # =====================================================
    # Unsubscribe
    # =====================================================

    async def _unsubscribe_code(
        self,
        quote_ctx,
        code,
    ):

        ret, data = (
            await asyncio.to_thread(
                quote_ctx.unsubscribe,

                [code],

                [
                    SubType.QUOTE
                ],
            )
        )

        if ret != RET_OK:

            print(
                "[MOOMOO UNSUBSCRIBE ERROR] "
                f"{code} | {data}"
            )

            return False

        print(
            "[MOOMOO UNSUBSCRIBE] "
            f"{code}"
        )

        return True

    # =====================================================
    # 同步数据库 Asset -> Moomoo Subscription
    # =====================================================

    async def _refresh_market_states(
        self,
        quote_ctx,
        codes,
    ):

        us_codes = sorted(
            code
            for code in codes
            if code.startswith(
                "US."
            )
        )

        if not us_codes:
            return

        try:

            ret, data = (
                await asyncio.to_thread(
                    quote_ctx.get_market_state,
                    us_codes,
                )
            )

            if ret != RET_OK:

                print(
                    "[MOOMOO MARKET STATE ERROR]",
                    data,
                )

                return

            for _, row in data.iterrows():

                code = (
                    str(
                        row.get(
                            "code"
                        )
                    )
                    .strip()
                    .upper()
                )

                raw_state = (
                    row.get(
                        "market_state"
                    )
                )

                session = (
                    self
                    ._map_moomoo_market_state(
                        raw_state
                    )
                )

                if session is None:
                    continue

                old_session = (
                    self._market_states.get(
                        code
                    )
                )

                self._market_states[
                    code
                ] = session

                # 只在阶段发生变化时打印
                if (
                    old_session
                    != session
                ):

                    print(
                        "[MOOMOO SESSION] "
                        f"{code} | "
                        f"{raw_state} "
                        f"-> {session}"
                    )

        except Exception as error:

            print(
                "[MOOMOO MARKET STATE ERROR]",
                error,
            )

    async def _sync_subscriptions(
        self,
        quote_ctx,
        code_loader,
        current_codes,
        subscribed_at,
    ):

        try:

            desired_codes = (
                self._normalize_codes(
                    code_loader()
                )
            )

        except Exception as error:

            print(
                "[MOOMOO ASSET LOAD ERROR]",
                error,
            )

            return

        loop = (
            asyncio.get_running_loop()
        )

        now = (
            loop.time()
        )

        # =============================================
        # 新增
        # =============================================

        to_add = (
            desired_codes
            - current_codes
        )

        for code in sorted(
            to_add
        ):

            success = (
                await self._subscribe_code(
                    quote_ctx,
                    code,
                )
            )

            if success:

                current_codes.add(
                    code
                )

                subscribed_at[
                    code
                ] = loop.time()

        # =============================================
        # 删除
        #
        # 新订阅不足 60 秒时，
        # 暂时不取消。
        # =============================================

        to_remove = (
            current_codes
            - desired_codes
        )

        for code in sorted(
            to_remove
        ):

            start_time = (
                subscribed_at.get(
                    code
                )
            )

            if (
                start_time is not None
                and (
                    now
                    - start_time
                ) < 60
            ):

                continue

            success = (
                await self._unsubscribe_code(
                    quote_ctx,
                    code,
                )
            )

            if success:

                current_codes.discard(
                    code
                )

                subscribed_at.pop(
                    code,
                    None,
                )

                self._last_active_prices.pop(
                    code,
                    None,
                )
                self._market_states.pop(
                    code,
                    None,
                )

                self._session_price_state.pop(
                    code,
                    None,
                )

    # =====================================================
    # Subscription Refresh Loop
    # =====================================================

    async def _subscription_refresh_loop(
        self,
        quote_ctx,
        code_loader,
        current_codes,
        subscribed_at,
        refresh_seconds,
    ):

        while True:
            await asyncio.sleep(
                refresh_seconds
            )

            await self._sync_subscriptions(
                quote_ctx=quote_ctx,
                code_loader=code_loader,
                current_codes=current_codes,
                subscribed_at=subscribed_at,
            )

            await self._refresh_market_states(
                quote_ctx=quote_ctx,
                codes=current_codes,
            )

    # =====================================================
    # Dynamic Streaming
    # =====================================================

    async def stream_markets_dynamic(
        self,
        code_loader,
        refresh_seconds=5,
    ):

        loop = (
            asyncio.get_running_loop()
        )

        queue = asyncio.Queue(
            maxsize=5000
        )

        current_codes = set()

        subscribed_at = {}

        quote_ctx = (
            OpenQuoteContext(
                host=self.host,
                port=self.port,
            )
        )

        handler = (
            _MoomooQuoteHandler(
                loop=loop,
                queue=queue,
                provider=self,
            )
        )

        quote_ctx.set_handler(
            handler
        )

        refresh_task = None

        try:

            print()
            print(
                "Moomoo OpenD "
                "连接成功"
            )

            # 第一次立即同步
            await self._sync_subscriptions(
                quote_ctx=quote_ctx,
                code_loader=code_loader,
                current_codes=current_codes,
                subscribed_at=subscribed_at,
            )

            # 后续每 N 秒同步一次
            refresh_task = (
                asyncio.create_task(
                    self._subscription_refresh_loop(
                        quote_ctx=quote_ctx,
                        code_loader=code_loader,
                        current_codes=current_codes,
                        subscribed_at=subscribed_at,
                        refresh_seconds=refresh_seconds,
                    )
                )
            )

            while True:

                snapshot = (
                    await queue.get()
                )

                yield snapshot

        except asyncio.CancelledError:

            raise

        finally:

            if (
                refresh_task
                is not None
            ):

                refresh_task.cancel()

            quote_ctx.close()

    # =====================================================
    # Fixed Streaming Compatibility
    #
    # 保留旧接口，避免测试代码失效。
    # =====================================================

    async def stream_markets(
        self,
        codes,
    ):

        fixed_codes = (
            self._normalize_codes(
                codes
            )
        )

        def code_loader():

            return fixed_codes

        async for snapshot in (
            self.stream_markets_dynamic(
                code_loader=code_loader,
                refresh_seconds=3600,
            )
        ):

            yield snapshot