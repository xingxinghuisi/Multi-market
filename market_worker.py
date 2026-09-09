import asyncio
from datetime import (
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
    AlertRule,
    Asset,
)
from notification_service import (
    send_alert_notification,
)
from providers.binance import (
    BinanceSpotProvider,
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
        BinanceSpotProvider()
    )

    # =====================================================
    # 只有一个 WebSocket
    # =====================================================

    async for snapshot in (
        provider.stream_markets(
            symbols
        )
    ):

        symbol = (
            snapshot.symbol
        )

        asset_id = (
            assets.get(
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


# =========================================================
# Main
# =========================================================

async def main():

    await run_binance_batch()


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