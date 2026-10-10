"""Additive storage for public Hyperliquid positions; separate from Binance trades."""
from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class WhaleSubscription(Base):
    __tablename__ = "whale_position_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "coin"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    coin: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    min_position_usd: Mapped[float] = mapped_column(Float, default=1000000)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=300)
    started_ms: Mapped[int] = mapped_column(Integer)


class WhaleAddress(Base):
    __tablename__ = "whale_addresses"
    address: Mapped[str] = mapped_column(String(42), primary_key=True)
    discovered_ms: Mapped[int] = mapped_column(Integer)
    last_trade_ms: Mapped[int] = mapped_column(Integer)
    checked_ms: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_ms: Mapped[int] = mapped_column(Integer, default=0)
    next_check_ms: Mapped[int] = mapped_column(Integer, default=0, index=True)
    positions: Mapped[dict] = mapped_column(JSON, default=dict)


class WhalePositionEvent(Base):
    __tablename__ = "whale_position_events"
    event_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    address: Mapped[str] = mapped_column(String(42), index=True)
    coin: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    qualifying_usd: Mapped[float] = mapped_column(Float)
    observed_ms: Mapped[int] = mapped_column(Integer, index=True)
    dispatched_ms: Mapped[int] = mapped_column(Integer, default=0, index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class WhalePositionDelivery(Base):
    __tablename__ = "whale_position_deliveries"
    __table_args__ = (UniqueConstraint("user_id", "event_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_key: Mapped[str] = mapped_column(ForeignKey("whale_position_events.event_key"))
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id"))
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    next_retry_ms: Mapped[int] = mapped_column(Integer, default=0)


class WhaleRuntime(Base):
    __tablename__ = "whale_position_runtime"
    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


def initialize_whale_tables(engine):
    # Existing users, assets, rules and data are never rewritten.
    Base.metadata.create_all(engine, tables=[WhaleSubscription.__table__, WhaleAddress.__table__,
        WhalePositionEvent.__table__, WhalePositionDelivery.__table__, WhaleRuntime.__table__], checkfirst=True)
