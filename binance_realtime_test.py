import asyncio
from datetime import (
    timedelta,
    timezone,
)

from providers.binance import (
    BinanceSpotProvider,
)


# =========================================================
# 香港 / 新加坡 / 台湾
# UTC+8
# =========================================================

UTC8 = timezone(
    timedelta(hours=8)
)


async def main():

    provider = (
        BinanceSpotProvider()
    )

    symbol = "BTCUSDT"

    print()
    print("=" * 90)

    print(
        "Market Radar - "
        "Binance Realtime Test"
    )

    print("=" * 90)

    print(
        "Crypto 今日涨跌口径："
        "UTC+8 00:00 → 当前价格"
    )

    print("=" * 90)

    print()

    async for snapshot in (
        provider.stream_market(
            symbol
        )
    ):

        # =============================================
        # 行情时间转换成 UTC+8
        # =============================================

        market_time = (
            snapshot
            .event_time
            .astimezone(
                UTC8
            )
        )

        time_text = (
            market_time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        # =============================================
        # 输出
        # =============================================

        print(
            f"{time_text} | "
            f"{snapshot.symbol} | "
            f"现价 "
            f"{snapshot.price:,.2f} | "
            f"00:00开盘 "
            f"{snapshot.reference_price:,.2f} | "
            f"今日涨跌 "
            f"{snapshot.change_amount:+,.2f} | "
            f"{snapshot.change_pct:+.2f}%"
        )


if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print()
        print(
            "实时行情测试已停止。"
        )