from datetime import datetime

from sqlalchemy import select

from alert_service import process_rule
from database import SessionLocal
from models import (
    AlertRule,
    AlertState,
    Asset,
)


def find_test_rule(session):
    """
    找到 SK Hynix +3% 向上突破规则
    """

    statement = (
        select(AlertRule)
        .join(
            Asset,
            AlertRule.asset_id == Asset.id,
        )
        .where(
            Asset.symbol == "000660",
            Asset.venue == "KRX",
            AlertRule.metric == "change_pct",
            AlertRule.operator == "crossing_up",
            AlertRule.value == 3.0,
        )
    )

    return session.scalar(statement)


def reset_rule_state(
    session,
    rule,
):
    """
    清除之前的 AlertState，
    保证每次测试从全新状态开始
    """

    state = session.scalar(
        select(AlertState).where(
            AlertState.rule_id == rule.id
        )
    )

    if state:
        session.delete(state)
        session.commit()

        print(
            "♻️ 已清除旧 AlertState"
        )


def main():

    # 模拟盘中行情
    sequence = [
        ("09:30", 2.50),
        ("09:35", 3.10),
        ("09:40", 3.50),
        ("09:50", 2.95),
        ("10:00", 2.70),
        ("10:10", 3.05),
    ]

    with SessionLocal() as session:

        rule = find_test_rule(
            session
        )

        if not rule:

            print(
                "❌ 没有找到 SK Hynix +3% 测试规则"
            )

            print(
                "请先运行：python init_db.py"
            )

            return

        print(
            f"找到规则：Rule ID {rule.id}"
        )

        reset_rule_state(
            session,
            rule,
        )

        print()
        print("=" * 70)
        print(
            "Database Alert Engine Test"
        )
        print("=" * 70)
        print()

        for (
            time_text,
            change_pct,
        ) in sequence:

            hour, minute = map(
                int,
                time_text.split(":")
            )

            now = datetime(
                2026,
                9,
                9,
                hour,
                minute,
            )

            market_data = {
                "price": 1856000,
                "previous_close": 1793000,
                "change_pct": change_pct,
            }

            result = process_rule(
                session,
                rule,
                market_data,
                now=now,
            )

            session.commit()

            print(
                f"{time_text} | "
                f"{change_pct:+.2f}% | "
                f"{result['status']}"
            )

            if (
                result["status"]
                == "triggered"
            ):

                print(
                    "      🔔 Triggered"
                )

            elif (
                result["status"]
                == "rearmed"
            ):

                print(
                    "      ✅ Rearmed"
                )

        print()
        print("=" * 70)

    # =====================================================
    # 重新打开数据库
    # 验证状态确实被永久保存
    # =====================================================

    with SessionLocal() as session:

        rule = find_test_rule(
            session
        )

        state = session.scalar(
            select(AlertState).where(
                AlertState.rule_id == rule.id
            )
        )

        print()
        print(
            "数据库最终状态："
        )

        print(
            f"Rule ID："
            f"{rule.id}"
        )

        print(
            f"Armed："
            f"{state.armed}"
        )

        print(
            f"Last Value："
            f"{state.last_value}"
        )

        print(
            f"Trigger Count："
            f"{state.trigger_count}"
        )

        print(
            f"Last Triggered："
            f"{state.last_triggered_at}"
        )


if __name__ == "__main__":
    main()