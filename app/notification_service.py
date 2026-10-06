from datetime import (
    datetime,
    timezone,
    timedelta,
)

from sqlalchemy import func, select

from models import (
    AlertRule,
    Notification,
    User,
)
from telegram_service import (
    CHAT_ID,
    send_telegram_message,
)


UTC8 = timezone(
    timedelta(hours=8)
)


def get_display_rule_number(
    db,
    rule,
) -> int:

    rules_before = db.scalar(
        select(func.count())
        .select_from(AlertRule)
        .where(
            AlertRule.user_id == rule.user_id,
            AlertRule.id < rule.id,
        )
    ) or 0

    return int(rules_before) + 1


def format_trigger_time(
    event_time,
):

    if not isinstance(
        event_time,
        datetime,
    ):

        event_time = datetime.now(
            timezone.utc
        )

    # 当前 Binance Futures event_time
    # 为 naive UTC，统一补 UTC 时区。
    if event_time.tzinfo is None:

        event_time = (
            event_time.replace(
                tzinfo=timezone.utc
            )
        )

    local_time = (
        event_time.astimezone(
            UTC8
        )
    )

    return (
        f"{local_time.year}年"
        f"{local_time.month}月"
        f"{local_time.day}日 "
        f"{local_time:%H:%M:%S}"
    )


def build_alert_message(
    rule,
    asset,
    snapshot,
    result,
    rule_number=None,
) -> str:

    if rule_number is None:
        rule_number = rule.id

    trigger_time_text = (
        format_trigger_time(
            snapshot.event_time
        )
    )

    # =====================================================
    # 方向
    # =====================================================

    # =====================================================
    # Step Alert
    # =====================================================

    if rule.operator == "step":

        direction = result.get(
            "direction"
        )

        step_size = float(
            result.get(
                "step_size",
                rule.value,
            )
        )

        anchor_before = float(
            result.get(
                "anchor_before"
            )
        )

        anchor_after = float(
            result.get(
                "anchor_after"
            )
        )

        current_value = float(
            result.get(
                "current_value",
                snapshot.price,
            )
        )

        currency = (
            asset.currency
            or ""
        )

        if direction == "up":

            direction_text = (
                "步进上涨"
            )

            direction_icon = "📈"

        else:

            direction_text = (
                "步进下跌"
            )

            direction_icon = "📉"


        next_up = (
            anchor_after
            + step_size
        )

        next_down = (
            anchor_after
            - step_size
        )


        message = (
            f"{direction_icon} "
            f"{asset.symbol} "
            f"{direction_text} · 当前价 "
            f"{current_value:,.2f} "
            f"{currency}\n\n"

            f"步长："
            f"{step_size:,.2f} "
            f"{currency}\n\n"

            f"原锚点："
            f"{anchor_before:,.2f}\n"

            f"新锚点："
            f"{anchor_after:,.2f}\n\n"

            f"↑ 下一上涨提醒："
            f"{next_up:,.2f}\n"

            f"↓ 下一下跌提醒："
            f"{next_down:,.2f}\n\n"

            f"🕐 触发时间："
            f"{trigger_time_text}\n\n"

            f"Rule #{rule_number}"
        )

        return message


    if rule.operator == "crossing_up":

        action_text = "向上突破"

    elif rule.operator == "crossing_down":

        action_text = "向下跌破"

    else:

        action_text = rule.operator

    # =====================================================
    # Metric 名称
    # =====================================================

    if rule.metric == "price":

        metric_text = "价格"

    elif rule.metric == "change_pct":

        metric_text = "今日涨跌幅"

    elif rule.metric == "price_change":

        metric_text = "今日涨跌额"

    else:

        metric_text = rule.metric

    # =====================================================
    # 今日涨跌
    # =====================================================

    change_text = (
        f"{snapshot.change_pct:+.2f}%"
        if snapshot.change_pct is not None
        else "-"
    )

    # =====================================================
    # 消息
    # =====================================================

    direction_icon = (
        "📈" if rule.operator == "crossing_up" else "📉"
    )

    message = (
        f"{direction_icon} {asset.symbol} {action_text} · 当前价 "
        f"{snapshot.price:,.2f} {asset.currency}\n\n"
        f"监控指标：{metric_text}\n"
        f"当前价格：{snapshot.price:,.2f} "
        f"{asset.currency}\n"
        f"触发阈值：{rule.value:,.2f}\n"
        f"今日涨跌：{change_text}\n"
        f"Previous："
        f"{result.get('previous_value')}\n"
        f"Current："
        f"{result.get('current_value')}\n\n"
        f"Rule #{rule_number}"
    )

    return message


def create_notification(
    db,
    rule,
    asset,
    message,
):

    # =====================================================
    # 通知标题
    # =====================================================

    if rule.operator == "crossing_up":

        action_text = "向上突破"

    elif rule.operator == "crossing_down":

        action_text = "向下跌破"

    else:

        action_text = rule.operator

    title = (
        f"{asset.symbol} {action_text}"
    )

    # =====================================================
    # 创建 Notification
    # =====================================================

    notification = Notification(

        user_id=rule.user_id,

        asset_id=asset.id,

        rule_id=rule.id,

        # 必填
        category="market_alert",

        # 必填
        title=title,

        message=message,

        channel="telegram",

        status="pending",
    )

    db.add(
        notification
    )

    db.flush()

    return notification

    notification = Notification(

        user_id=rule.user_id,

        asset_id=asset.id,

        rule_id=rule.id,

        channel="telegram",

        status="pending",

        message=message,

    )

    db.add(
        notification
    )

    db.flush()

    return notification


def send_alert_notification(
    db,
    rule,
    asset,
    snapshot,
    result,
):

    # =====================================================
    # 生成消息
    # =====================================================

    message = build_alert_message(
        rule=rule,
        asset=asset,
        snapshot=snapshot,
        result=result,
        rule_number=get_display_rule_number(db, rule),
    )

    # =====================================================
    # 先写数据库
    # =====================================================

    notification = (
        create_notification(
            db=db,
            rule=rule,
            asset=asset,
            message=message,
        )
    )

    user = db.get(User, rule.user_id)
    target = user.telegram_chat_id or (CHAT_ID if user.username == "default" else None) if user else None
    if not target:
        notification.channel = "in_app"
        notification.status = "in_app"
        return notification

    # =====================================================
    # Telegram
    # =====================================================

    try:

        telegram_sent = (
            send_telegram_message(
                message,
                chat_id=target,
            )
        )

        if not telegram_sent:
            raise RuntimeError(
                "Telegram message send failed"
            )

        notification.status = (
            "sent"
        )

        # 如果模型里有 sent_at
        if hasattr(
            notification,
            "sent_at",
        ):

            notification.sent_at = (
                datetime.now(
                    timezone.utc
                )
            )

        print(
            f"[TELEGRAM SENT] "
            f"Notification ID="
            f"{notification.id}"
        )

    except Exception as error:

        notification.status = (
            "failed"
        )

        print(
            f"[TELEGRAM FAILED] "
            f"{error}"
        )

    return notification
