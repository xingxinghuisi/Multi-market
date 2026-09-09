import asyncio

from providers.registry import provider_registry

from datetime import (
    date,
    datetime,
    timedelta,
    timezone,
)

from sqlalchemy import select

from alert_service import (
    process_rule,
)
from database import (
    SessionLocal,
)
from models import (
    Asset,
    AlertRule,
    MarketQuote,
    DailyPrice,
)
from notification_service import (
    send_alert_notification,
)


# =========================================================
# Market Radar V0.8
#
# Binance Batch Worker
# =========================================================


HEARTBEAT_SECONDS = 10


# =========================================================
# UTC+8
# =========================================================

UTC8 = timezone(
    timedelta(hours=8)
)


# =========================================================
# 每个资产独立 Heartbeat
# =========================================================

last_heartbeats = {}


def format_rule(
    rule: AlertRule,
) -> str:

    return (
        f"Rule {rule.id} | "
        f"{rule.metric} | "
        f"{rule.operator} | "
        f"{rule.value}"
    )


def save_market_quote(
    db,
    asset_id: int,
    snapshot,
):

    quote = db.scalar(
        select(
            MarketQuote
        ).where(
            MarketQuote.asset_id
            == asset_id
        )
    )

    if quote is None:

        quote = MarketQuote(
            asset_id=asset_id,
            price=snapshot.price,
            reference_price=snapshot.reference_price,
            change_amount=snapshot.change_amount,
            change_pct=snapshot.change_pct,
            open=snapshot.open,
            high=snapshot.high,
            low=snapshot.low,
            volume=snapshot.volume,
            quote_volume=snapshot.quote_volume,
            event_time=snapshot.event_time,
            session_date=snapshot.session_date,
            reference_type=snapshot.reference_type,
            reference_timezone=snapshot.reference_timezone,
        )

        db.add(
            quote
        )

    else:

        quote.price = (
            snapshot.price
        )

        quote.reference_price = (
            snapshot.reference_price
        )

        quote.change_amount = (
            snapshot.change_amount
        )

        quote.change_pct = (
            snapshot.change_pct
        )

        quote.open = (
            snapshot.open
        )

        quote.high = (
            snapshot.high
        )

        quote.low = (
            snapshot.low
        )

        quote.volume = (
            snapshot.volume
        )

        quote.quote_volume = (
            snapshot.quote_volume
        )

        quote.event_time = (
            snapshot.event_time
        )

        quote.session_date = (
            snapshot.session_date
        )

        quote.reference_type = (
            snapshot.reference_type
        )

        quote.reference_timezone = (
            snapshot.reference_timezone
        )

    db.commit()


def save_daily_price(
    db,
    asset_id: int,
    snapshot,
):

    if not snapshot.session_date:

        return

    if isinstance(
        snapshot.session_date,
        date,
    ):

        session_date = (
            snapshot.session_date
        )

    else:

        session_date = (
            datetime.strptime(
                snapshot.session_date,
                "%Y-%m-%d",
            ).date()
        )

    daily_price = db.scalar(
        select(
            DailyPrice
        ).where(
            DailyPrice.asset_id
            == asset_id,

            DailyPrice.date
            == session_date,
        )
    )

    if daily_price is None:

        daily_price = DailyPrice(
            asset_id=asset_id,
            date=session_date,
            open=snapshot.open,
            high=snapshot.high,
            low=snapshot.low,
            close=snapshot.price,
            volume=snapshot.volume,
            change_pct=snapshot.change_pct,
        )

        db.add(
            daily_price
        )

    else:

        daily_price.open = snapshot.open
        daily_price.high = snapshot.high
        daily_price.low = snapshot.low
        daily_price.close = snapshot.price
        daily_price.volume = snapshot.volume
        daily_price.change_pct = snapshot.change_pct

    db.commit()
# =========================================================
# Snapshot
# ↓
# Rule
# ↓
# Alert Engine
# ↓
# Notification
# =========================================================

def process_snapshot(
    asset_id: int,
    snapshot,
):

    market_data = (
        snapshot.to_dict()
    )

    with SessionLocal() as db:

        asset = db.get(
            Asset,
            asset_id,
        )

        if asset is None:

            return []

        if not asset.enabled:

            return []

        save_market_quote(
            db=db,
            asset_id=asset.id,
            snapshot=snapshot,
        )

        save_daily_price(
            db=db,
            asset_id=asset.id,
            snapshot=snapshot,
        )

        # =================================================
        # 保存最新市场行情
        # =================================================

        save_market_quote(
            db=db,
            asset_id=asset.id,
            snapshot=snapshot,
        )

        symbol = (
            asset.symbol
        )

        rules = db.scalars(
            select(
                AlertRule
            )
            .where(
                AlertRule.asset_id
                == asset.id,

                AlertRule.enabled
                == True,
            )
            .order_by(
                AlertRule.id
            )
        ).all()

        results = []

        for rule in rules:

            rule_id = (
                rule.id
            )

            try:

                result = process_rule(
                    session=db,
                    rule=rule,
                    market_data=(
                        market_data
                    ),
                    now=(
                        snapshot.event_time
                    ),
                )

                # =========================================
                # Trigger
                # =========================================

                if (
                    result.get(
                        "status"
                    )
                    == "triggered"
                ):

                    send_alert_notification(
                        db=db,
                        rule=rule,
                        asset=asset,
                        snapshot=snapshot,
                        result=result,
                    )

                results.append(
                    {
                        "rule_id": (
                            rule.id
                        ),

                        "metric": (
                            rule.metric
                        ),

                        "operator": (
                            rule.operator
                        ),

                        "value": (
                            rule.value
                        ),

                        "status": (
                            result.get(
                                "status"
                            )
                        ),

                        "previous_value":
                            result.get(
                                "previous_value"
                            ),

                        "current_value":
                            result.get(
                                "current_value"
                            ),
                    }
                )

            except Exception as error:

                db.rollback()

                print()
                print(
                    "Alert Rule "
                    "处理失败"
                )

                print(
                    f"Asset："
                    f"{symbol}"
                )

                print(
                    f"Rule ID："
                    f"{rule_id}"
                )

                print(
                    f"错误："
                    f"{error}"
                )

                print()

        db.commit()

        return results


# =========================================================
# 数据库加载 Binance Assets
# =========================================================

def load_binance_assets():

    with SessionLocal() as db:

        assets = db.scalars(
            select(
                Asset
            )
            .where(
                Asset.enabled
                == True,

                Asset.provider
                == "BINANCE",
            )
            .order_by(
                Asset.id
            )
        ).all()

        return {
            asset.symbol: (
                asset.id
            )

            for asset
            in assets
        }

def load_binance_symbols():
    """
    Provider 每隔几秒调用一次。

    只返回当前数据库中：
    - enabled = true
    - provider = BINANCE

    的 Symbol。
    """

    assets = (
        load_binance_assets()
    )

    return list(
        assets.keys()
    )

def load_krx_assets():

    with SessionLocal() as db:

        assets = db.scalars(
            select(
                Asset
            )
            .where(
                Asset.enabled == True,
                Asset.provider == "PYKRX",
                Asset.venue == "KRX",
            )
            .order_by(
                Asset.id
            )
        ).all()

        return {
            asset.symbol: asset.id
            for asset in assets
        }

# =========================================================
# 打印 Alert 结果
# =========================================================

def print_alert_results(
    symbol: str,
    snapshot,
    results,
):

    for result in results:

        status = (
            result[
                "status"
            ]
        )

        # =============================================
        # INIT
        # =============================================

        if (
            status
            == "initialized"
        ):

            print(
                f"[INIT] "
                f"{symbol} | "
                f"Rule "
                f"{result['rule_id']} | "
                f"{result['metric']} | "
                f"{result['operator']} | "
                f"{result['value']} | "
                f"当前值="
                f"{result['current_value']}"
            )

        # =============================================
        # REARM
        # =============================================

        elif (
            status
            == "rearmed"
        ):

            print(
                f"[REARMED] "
                f"{symbol} | "
                f"Rule "
                f"{result['rule_id']}"
            )

        # =============================================
        # COOLDOWN
        # =============================================

        elif (
            status
            == "suppressed_cooldown"
        ):

            print(
                f"[COOLDOWN] "
                f"{symbol} | "
                f"Rule "
                f"{result['rule_id']}"
            )

        # =============================================
        # TRIGGERED
        # =============================================

        elif (
            status
            == "triggered"
        ):

            market_time = (
                snapshot
                .event_time
                .astimezone(
                    UTC8
                )
            )

            print()
            print(
                "🚨" * 15
            )

            print(
                "ALERT TRIGGERED"
            )

            print(
                f"Asset："
                f"{symbol}"
            )

            print(
                f"Rule ID："
                f"{result['rule_id']}"
            )

            print(
                f"Metric："
                f"{result['metric']}"
            )

            print(
                f"Operator："
                f"{result['operator']}"
            )

            print(
                f"Threshold："
                f"{result['value']}"
            )

            print(
                f"Previous："
                f"{result['previous_value']}"
            )

            print(
                f"Current："
                f"{result['current_value']}"
            )

            print(
                f"Price："
                f"{snapshot.price:,.8f}"
            )

            if (
                snapshot.change_pct
                is not None
            ):

                print(
                    f"UTC+8 今日涨跌："
                    f"{snapshot.change_pct:+.2f}%"
                )

            print(
                "Time UTC+8："
                f"{market_time.strftime(
                    '%Y-%m-%d %H:%M:%S'
                )}"
            )

            print(
                "🚨" * 15
            )

            print()


# =========================================================
# Heartbeat
# =========================================================

def print_heartbeat(
    symbol: str,
    snapshot,
):

    now = (
        datetime.now()
    )

    last = (
        last_heartbeats.get(
            symbol
        )
    )

    if (
        last is not None
        and
        (
            now
            - last
        )
        < timedelta(
            seconds=(
                HEARTBEAT_SECONDS
            )
        )
    ):

        return

    change_text = "-"

    if (
        snapshot.change_pct
        is not None
    ):

        change_text = (
            f"{snapshot.change_pct:+.2f}%"
        )

    market_time = (
        snapshot
        .event_time
        .astimezone(
            UTC8
        )
        .strftime(
            "%H:%M:%S"
        )
    )

    print(
        f"[LIVE] "
        f"{market_time} | "
        f"{symbol} | "
        f"{snapshot.price:,.8f} | "
        f"UTC+8 今日 "
        f"{change_text}"
    )

    last_heartbeats[
        symbol
    ] = now


# =========================================================
# Binance Batch Worker
# =========================================================

async def run_binance_batch():

    assets = (
        load_binance_assets()
    )

    if not assets:

        print(
            "没有 Binance Asset。"
        )

        return

    symbols = list(
        assets.keys()
    )

    print()
    print(
        "=" * 80
    )

    print(
        "Market Radar V0.8"
    )

    print(
        "Binance Batch "
        "Realtime Worker"
    )

    print(
        "=" * 80
    )

    print()

    print(
        "Binance Assets："
    )

    for (
        symbol,
        asset_id,
    ) in assets.items():

        print(
            f"- {symbol} "
            f"(Asset ID="
            f"{asset_id})"
        )

    print()

    provider = (
        provider_registry.get(
            "BINANCE"
        )
    )

    # =====================================================
    # 只有一个 WebSocket
    # =====================================================

    async for snapshot in (
            provider.stream_markets_dynamic(
                symbol_loader=(
                        load_binance_symbols
                ),
                refresh_seconds=5,
            )
    ):

        symbol = (
            snapshot.symbol
        )

        # =========================================================
        # 每次行情都根据数据库重新解析 Asset ID
        #
        # V0.9 动态资产需要这样做。
        # =========================================================

        current_assets = (
            load_binance_assets()
        )

        asset_id = (
            current_assets.get(
                symbol
            )
        )

        if asset_id is None:

            continue

        results = (
            process_snapshot(
                asset_id=(
                    asset_id
                ),
                snapshot=(
                    snapshot
                ),
            )
        )

        print_alert_results(
            symbol=(
                symbol
            ),
            snapshot=(
                snapshot
            ),
            results=(
                results
            ),
        )

        print_heartbeat(
            symbol=(
                symbol
            ),
            snapshot=(
                snapshot
            ),
        )

def print_krx_snapshot(
    symbol: str,
    snapshot,
    results,
):

    print()
    print(
        f"[KRX] {symbol}"
    )

    print(
        f"Price: "
        f"{snapshot.price:,.0f} KRW"
    )

    print(
        f"Previous Close: "
        f"{snapshot.reference_price:,.0f} KRW"
    )

    print(
        f"Change: "
        f"{snapshot.change_amount:+,.0f} KRW"
    )

    print(
        f"Change %: "
        f"{snapshot.change_pct:+.2f}%"
    )

    print(
        f"Session: "
        f"{snapshot.session_date}"
    )

    for result in results:

        status = result.get(
            "status"
        )

        if status in {
            "triggered",
            "rearmed",
        }:

            print(
                f"[RULE] "
                f"ID={result['rule_id']} "
                f"{status}"
            )


async def run_krx_polling(
    refresh_seconds: int = 30,
):

    provider = (
        provider_registry.get(
            "PYKRX"
        )
    )

    print()
    print(
        "=" * 80
    )

    print(
        "KRX Polling Worker"
    )

    print(
        "=" * 80
    )

    while True:

        assets = (
            load_krx_assets()
        )

        if not assets:

            print(
                "[KRX] "
                "没有启用的 KRX Asset"
            )

            await asyncio.sleep(
                refresh_seconds
            )

            continue

        for (
            symbol,
            asset_id,
        ) in assets.items():

            try:

                # =====================================
                # pykrx 是同步网络请求
                #
                # 放入线程，避免阻塞 Binance WebSocket
                # =====================================

                snapshot = await asyncio.to_thread(
                    provider.get_snapshot,
                    symbol,
                )

                if snapshot is None:

                    print(
                        f"[KRX] "
                        f"{symbol} "
                        f"没有行情数据"
                    )

                    continue

                # =====================================
                # 查询过程中 Asset 可能已被关闭
                #
                # process_snapshot 内部还会再次检查
                # enabled
                # =====================================

                results = (
                    process_snapshot(
                        asset_id=asset_id,
                        snapshot=snapshot,
                    )
                )

                print_krx_snapshot(
                    symbol=symbol,
                    snapshot=snapshot,
                    results=results,
                )

            except Exception as error:

                print()
                print(
                    f"[KRX ERROR] "
                    f"{symbol}"
                )

                print(
                    f"Error: {error}"
                )

                print()

        await asyncio.sleep(
            refresh_seconds
        )
# =========================================================
# Main
# =========================================================

async def main():

    await asyncio.gather(
        run_binance_batch(),
        run_krx_polling(),
    )


if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print()
        print(
            "Market Radar "
            "V0.8 Worker 已停止。"
        )