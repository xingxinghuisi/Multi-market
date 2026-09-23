import os

from datetime import (
    datetime,
    timezone,
)

from sqlalchemy import (
    select,
)

from models import (
    Notification,
    User,
    WatchlistItem,
)

from telegram_service import (
    send_telegram_message,
)


NEWS_ALERT_IMPACT_MIN = int(
    os.getenv(
        "NEWS_ALERT_IMPACT_MIN",
        "60",
    )
)

NEWS_ALERT_RELEVANCE_MIN = int(
    os.getenv(
        "NEWS_ALERT_RELEVANCE_MIN",
        "70",
    )
)


def build_news_alert_message(
    asset,
    news,
    impact,
):

    if impact.sentiment == "positive":

        direction_text = "正面"

    elif impact.sentiment == "negative":

        direction_text = "负面"

    else:

        direction_text = "中性"

    reason = (
        impact.reason
        or "-"
    )

    source = (
        news.source
        or "-"
    )

    url = (
        news.url
        or ""
    )

    return (
        "📰 Market Radar 新闻提醒\n\n"

        f"资产：{asset.symbol}\n"
        f"名称：{asset.name}\n\n"

        f"方向：{direction_text}\n"
        f"影响强度："
        f"{impact.impact_score}/100\n"

        f"相关度："
        f"{impact.relevance_score}/100\n\n"

        f"标题：\n"
        f"{news.title}\n\n"

        f"AI 判断：\n"
        f"{reason}\n\n"

        f"来源：{source}\n"
        f"{url}"
    )


def maybe_send_news_notification(
    db,
    asset,
    news,
    impact,
):

    # =====================================================
    # 只推送 Groq 分析结果
    # =====================================================

    if (
        impact.analysis_source
        != "groq"
    ):

        return {
            "status": "skipped",
            "reason": "not_groq",
        }

    # =====================================================
    # 必须非中性
    # =====================================================

    if (
        impact.sentiment
        == "neutral"
    ):

        return {
            "status": "skipped",
            "reason": "neutral",
        }

    # =====================================================
    # 相关度
    # =====================================================

    relevance = (
        impact.relevance_score
    )

    if (
        relevance is None
        or relevance
        < NEWS_ALERT_RELEVANCE_MIN
    ):

        return {
            "status": "skipped",
            "reason": "low_relevance",
        }

    # =====================================================
    # 影响强度
    # =====================================================

    if (
        impact.impact_score
        < NEWS_ALERT_IMPACT_MIN
    ):

        return {
            "status": "skipped",
            "reason": "low_impact",
        }

    # =====================================================
    # 当前默认用户
    # =====================================================

    user = db.scalar(
        select(
            User
        )
        .where(
            User.username
            == "default"
        )
    )

    if user is None:

        return {
            "status": "skipped",
            "reason": "user_not_found",
        }

    # =====================================================
    # 必须已经关注
    # 且开启新闻
    # =====================================================

    watch = db.scalar(
        select(
            WatchlistItem
        )
        .where(
            WatchlistItem.user_id
            == user.id,

            WatchlistItem.asset_id
            == asset.id,

            WatchlistItem.news_enabled
            .is_(True),
        )
    )

    if watch is None:

        return {
            "status": "skipped",
            "reason": "not_watched",
        }

    # =====================================================
    # 查找已有通知
    # =====================================================

    notification = db.scalar(
        select(
            Notification
        )
        .where(
            Notification.user_id
            == user.id,

            Notification.news_id
            == news.id,

            Notification.asset_id
            == asset.id,

            Notification.category
            == "news_alert",
        )
    )

    # 已经成功发送过
    if (
        notification is not None
        and notification.status
        == "sent"
    ):

        return {
            "status": "duplicate",
            "notification_id":
                notification.id,
        }

    message = (
        build_news_alert_message(
            asset=asset,
            news=news,
            impact=impact,
        )
    )

    # =====================================================
    # 没有记录就创建
    # =====================================================

    if notification is None:

        notification = Notification(
            user_id=user.id,
            asset_id=asset.id,
            rule_id=None,
            news_id=news.id,
            category="news_alert",
            title=(
                f"{asset.symbol} "
                "高影响新闻"
            ),
            message=message,
            channel="telegram",
            status="pending",
        )

        db.add(
            notification
        )

        db.flush()

    else:

        # 之前发送失败，
        # 允许下一次重新尝试

        notification.message = (
            message
        )

        notification.status = (
            "pending"
        )

    # =====================================================
    # Telegram
    # =====================================================

    try:

        sent = (
            send_telegram_message(
                message
            )
        )

        if not sent:

            raise RuntimeError(
                "Telegram message "
                "send failed"
            )

        notification.status = (
            "sent"
        )

        notification.sent_at = (
            datetime.now(
                timezone.utc
            )
        )

        print(
            "[NEWS TELEGRAM SENT] "
            f"{asset.symbol} | "
            f"News ID={news.id} | "
            f"Notification ID="
            f"{notification.id}"
        )

        return {
            "status": "sent",
            "notification_id":
                notification.id,
        }

    except Exception as error:

        notification.status = (
            "failed"
        )

        print(
            "[NEWS TELEGRAM FAILED] "
            f"{asset.symbol} | "
            f"News ID={news.id} | "
            f"{type(error).__name__}: "
            f"{error}"
        )

        return {
            "status": "failed",
            "notification_id":
                notification.id,
            "error":
                type(error).__name__,
        }