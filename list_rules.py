from sqlalchemy import select

from database import SessionLocal
from models import (
    AlertRule,
    Stock,
    User,
)


def metric_name(
    metric,
):

    names = {
        "change_pct": "今日涨跌幅",
        "price": "当前价格",
        "price_change": "今日涨跌金额",
    }

    return names.get(
        metric,
        metric,
    )


def operator_name(
    operator,
):

    names = {
        "crossing_up": "向上突破",
        "crossing_down": "向下跌破",
    }

    return names.get(
        operator,
        operator,
    )


def main():

    with SessionLocal() as session:

        statement = (
            select(
                AlertRule,
                Stock,
                User,
            )
            .join(
                Stock,
                AlertRule.asset_id
                == Stock.id,
            )
            .join(
                User,
                AlertRule.user_id
                == User.id,
            )
            .order_by(
                AlertRule.id
            )
        )

        rows = session.execute(
            statement
        ).all()

        print()
        print("=" * 80)
        print(
            "Korea Market Radar - Alert Rules"
        )
        print("=" * 80)

        if not rows:

            print(
                "数据库中没有提醒规则。"
            )

            return

        for (
            rule,
            stock,
            user,
        ) in rows:

            print()

            print(
                f"Rule ID：{rule.id}"
            )

            print(
                f"用户：{user.username}"
            )

            print(
                f"股票："
                f"{stock.name} "
                f"({stock.ticker})"
            )

            print(
                f"指标："
                f"{metric_name(rule.metric)}"
            )

            print(
                f"方向："
                f"{operator_name(rule.operator)}"
            )

            print(
                f"阈值：{rule.value}"
            )

            print(
                f"Reset Buffer："
                f"{rule.reset_buffer}"
            )

            print(
                f"Cooldown："
                f"{rule.cooldown_seconds} 秒"
            )

            print(
                f"启用：{rule.enabled}"
            )

            print(
                "-" * 80
            )


if __name__ == "__main__":
    main()