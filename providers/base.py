from dataclasses import (
    asdict,
    dataclass,
)
from datetime import (
    date,
    datetime,
)
from typing import Any


@dataclass(slots=True)
class MarketSnapshot:
    """
    Market Radar 的统一行情数据结构。

    不管行情来自：

    - Binance
    - KRX
    - NASDAQ
    - NYSE
    - 其他市场

    最终都转换成 MarketSnapshot。

    Alert Engine 不需要知道
    行情到底来自哪个数据源。
    """

    # =====================================================
    # 资产信息
    # =====================================================

    symbol: str

    asset_type: str

    venue: str

    # =====================================================
    # 当前价格
    # =====================================================

    price: float

    # =====================================================
    # 今日涨跌基准价格
    #
    # Crypto:
    # UTC+8 当天 00:00 开盘价
    #
    # Stock:
    # 前一交易日收盘价
    # =====================================================

    reference_price: float | None

    # 当前价 - 基准价
    change_amount: float | None

    # 涨跌百分比
    change_pct: float | None

    # =====================================================
    # 当前交易日行情
    # =====================================================

    open: float | None

    high: float | None

    low: float | None

    volume: float | None

    quote_volume: float | None

    # =====================================================
    # 时间
    # =====================================================

    # 行情发生时间
    event_time: datetime

    # 这条行情属于哪个交易日
    session_date: date

    # =====================================================
    # 涨跌基准类型
    #
    # Crypto:
    # utc8_day_open
    #
    # Stock:
    # previous_close
    # =====================================================

    reference_type: str

    # =====================================================
    # 涨跌基准时区
    #
    # Crypto:
    # UTC+08:00
    #
    # Korea:
    # Asia/Seoul
    #
    # US:
    # America/New_York
    # =====================================================

    reference_timezone: str

    # =====================================================
    # 转换成普通 dict
    #
    # 以后直接交给 Alert Engine
    # =====================================================

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return asdict(
            self
        )