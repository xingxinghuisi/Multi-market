from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from database import Base


def utc_now():
    return datetime.now(
        timezone.utc
    )


# =========================================================
# 用户
# =========================================================

class User(Base):

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    username: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    telegram_chat_id: Mapped[str | None] = (
        mapped_column(
            String(100),
            nullable=True,
        )
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            default=utc_now,
        )
    )


# =========================================================
# 股票
# =========================================================

class Asset(Base):

    __tablename__ = "assets"

    __table_args__ = (
        UniqueConstraint(
            "venue",
            "segment",
            "symbol",
            name="uq_asset_venue_segment_symbol",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    # 例如：
    # 000660
    # BTCUSDT
    # AAPL
    symbol: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    # 显示名称
    # SK Hynix
    # Bitcoin / USDT
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    # stock / crypto / index / fund
    asset_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )

    # 交易场所
    # KRX / BINANCE / NASDAQ
    venue: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )

    # 更细市场
    # KOSPI / KOSDAQ / SPOT / USDT_PERPETUAL
    segment: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    # KRW / USDT / USD
    currency: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    # 当前使用什么行情 Provider
    # PYKRX / BINANCE
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )


# =========================================================
# 用户提醒规则
# =========================================================

class AlertRule(Base):

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id"),
        nullable=False,
        index=True,
    )

    metric: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    operator: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    reset_buffer: Mapped[float] = (
        mapped_column(
            Float,
            default=0,
        )
    )

    cooldown_seconds: Mapped[int] = (
        mapped_column(
            Integer,
            default=300,
        )
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            default=utc_now,
        )
    )


# =========================================================
# Alert Engine 状态
# =========================================================

class AlertState(Base):

    __tablename__ = "alert_states"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    rule_id: Mapped[int] = mapped_column(
        ForeignKey("alert_rules.id"),
        unique=True,
        nullable=False,
    )

    armed: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    last_value: Mapped[float | None] = (
        mapped_column(
            Float,
            nullable=True,
        )
    )

    last_triggered_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    trigger_count: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
        )
    )

    updated_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            default=utc_now,
            onupdate=utc_now,
        )
    )


# =========================================================
# 每日股票行情
# =========================================================

class DailyPrice(Base):

    __tablename__ = "daily_prices"

    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "date",
            name="uq_daily_price_asset_date",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id"),
        nullable=False,
        index=True,
    )

    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    open: Mapped[float] = mapped_column(
        Float
    )

    high: Mapped[float] = mapped_column(
        Float
    )

    low: Mapped[float] = mapped_column(
        Float
    )

    close: Mapped[float] = mapped_column(
        Float
    )

    volume: Mapped[int] = mapped_column(
        Integer
    )

    change_pct: Mapped[float] = (
        mapped_column(
            Float
        )
    )


# =========================================================
# 投资者资金流
# =========================================================

class InvestorFlow(Base):

    __tablename__ = "investor_flows"

    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "date",
            name="uq_flow_asset_date",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id"),
        nullable=False,
        index=True,
    )

    date: Mapped[date] = (
        mapped_column(
            Date,
            nullable=False,
            index=True,
        )
    )

    foreign_net: Mapped[float] = (
        mapped_column(
            Float,
            default=0,
        )
    )

    institution_net: Mapped[float] = (
        mapped_column(
            Float,
            default=0,
        )
    )

    retail_net: Mapped[float] = (
        mapped_column(
            Float,
            default=0,
        )
    )

    corporation_net: Mapped[float] = (
        mapped_column(
            Float,
            default=0,
        )
    )


# =========================================================
# 新闻
# =========================================================

class NewsItem(Base):

    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    url: Mapped[str] = mapped_column(
        Text,
        unique=True,
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    summary: Mapped[str | None] = (
        mapped_column(
            Text,
            nullable=True,
        )
    )

    published_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            default=utc_now,
        )
    )


# =========================================================
# 新闻对某只股票的影响
# =========================================================

class NewsImpact(Base):

    __tablename__ = "news_impacts"

    __table_args__ = (
        UniqueConstraint(
            "news_id",
            "asset_id",
            name="uq_news_asset",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    news_id: Mapped[int] = mapped_column(
        ForeignKey("news_items.id"),
        nullable=False,
        index=True,
    )

    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id"),
        nullable=False,
        index=True,
    )

    sentiment: Mapped[str] = (
        mapped_column(
            String(20),
            nullable=False,
        )
    )

    impact_score: Mapped[int] = (
        mapped_column(
            Integer,
            nullable=False,
        )
    )

    reason: Mapped[str | None] = (
        mapped_column(
            Text,
            nullable=True,
        )
    )


# =========================================================
# 通知记录
# =========================================================

class Notification(Base):

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    asset_id: Mapped[int | None] = (
        mapped_column(
            ForeignKey("assets.id"),
            nullable=True,
        )
    )

    rule_id: Mapped[int | None] = (
        mapped_column(
            ForeignKey("alert_rules.id"),
            nullable=True,
        )
    )

    category: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    channel: Mapped[str] = mapped_column(
        String(30),
        default="telegram",
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="pending",
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            default=utc_now,
        )
    )

    sent_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )