from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pykrx import stock

from providers.base import MarketSnapshot


KST = ZoneInfo(
    "Asia/Seoul"
)


class KRXProvider:

    provider_name = "PYKRX"

    def get_snapshot(
        self,
        symbol: str,
    ) -> MarketSnapshot | None:

        now = datetime.now(
            KST
        )

        # =================================================
        # 为了处理：
        #
        # 周末
        # 韩国节假日
        # 非交易日
        #
        # 向前查询最多 10 天
        # =================================================

        start_date = (
            now - timedelta(days=10)
        ).strftime("%Y%m%d")

        end_date = (
            now
        ).strftime("%Y%m%d")

        df = stock.get_market_ohlcv_by_date(
            start_date,
            end_date,
            symbol,
        )

        if (
            df is None
            or df.empty
        ):
            return None

        # =================================================
        # 至少需要一个交易日
        # =================================================

        latest = df.iloc[-1]

        latest_date = (
            df.index[-1]
            .strftime("%Y-%m-%d")
        )

        current_price = float(
            latest["종가"]
        )

        open_price = float(
            latest["시가"]
        )

        high_price = float(
            latest["고가"]
        )

        low_price = float(
            latest["저가"]
        )

        volume = float(
            latest["거래량"]
        )

        # =================================================
        # 前一交易日收盘
        # =================================================

        if len(df) >= 2:

            previous_close = float(
                df.iloc[-2]["종가"]
            )

        else:

            previous_close = (
                current_price
            )

        change_amount = (
            current_price
            - previous_close
        )

        if previous_close:

            change_pct = (
                change_amount
                / previous_close
                * 100
            )

        else:

            change_pct = 0.0

        return MarketSnapshot(

            symbol=symbol,

            asset_type="stock",

            venue="KRX",

            price=current_price,

            reference_price=previous_close,

            change_amount=change_amount,

            change_pct=change_pct,

            open=open_price,

            high=high_price,

            low=low_price,

            volume=volume,

            quote_volume=None,

            event_time=now,

            session_date=latest_date,

            reference_type=(
                "previous_close"
            ),

            reference_timezone=(
                "Asia/Seoul"
            ),
        )