"""Durable, account-owned checkpoints for aggregate Binance observations."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models import utc_now


class SmartMoneyState(Base):
    __tablename__ = "smart_money_states"
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("alert_subscriptions.id", ondelete="CASCADE"), primary_key=True)
    config_key: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="waiting")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


def initialize_smart_money_tables(engine):
    Base.metadata.create_all(engine, tables=[SmartMoneyState.__table__], checkfirst=True)
