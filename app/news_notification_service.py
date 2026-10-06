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
    CHAT_ID,
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
        "📰 MIRAO 新闻提醒\n\n"

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

    watches = db.scalars(
        select(WatchlistItem).where(
            WatchlistItem.asset_id == asset.id,
            WatchlistItem.news_enabled.is_(True),
        )
    ).all()
    if not watches:
        return {"status": "skipped", "reason": "not_watched"}

    message = build_news_alert_message(asset=asset, news=news, impact=impact)
    outcomes = []
    for watch in watches:
        user = db.get(User, watch.user_id)
        if user is None:
            continue
        notification = db.scalar(select(Notification).where(
            Notification.user_id == user.id,
            Notification.news_id == news.id,
            Notification.asset_id == asset.id,
            Notification.category == "news_alert",
        ))
        if notification is not None and notification.status in {"sent", "in_app"}:
            outcomes.append(notification.status)
            continue
        if notification is None:
            notification = Notification(
                user_id=user.id, asset_id=asset.id, rule_id=None, news_id=news.id,
                category="news_alert", title=f"{asset.symbol} 高影响新闻",
                message=message, channel="in_app", status="in_app",
            )
            db.add(notification)
            db.flush()
        else:
            notification.message = message
        target = user.telegram_chat_id or (CHAT_ID if user.username == "default" else None)
        if not target:
            notification.channel = "in_app"
            notification.status = "in_app"
            outcomes.append("in_app")
            continue
        notification.channel = "telegram"
        try:
            if not send_telegram_message(message, chat_id=target):
                raise RuntimeError("Telegram message send failed")
            notification.status = "sent"
            notification.sent_at = datetime.now(timezone.utc)
            outcomes.append("sent")
        except Exception as error:
            notification.status = "failed"
            outcomes.append("failed")
            print(f"[NEWS TELEGRAM FAILED] {asset.symbol} | News ID={news.id} | {type(error).__name__}: {error}")
    return {"status": "processed", "users": len(outcomes), "outcomes": outcomes}
