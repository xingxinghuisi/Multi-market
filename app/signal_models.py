"""Additive tables for candle checkpoints, paid requests and monthly cost notices."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models import utc_now


class TechnicalState(Base):
    __tablename__ = "technical_signal_states"
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("alert_subscriptions.id", ondelete="CASCADE"), primary_key=True)
    config_key: Mapped[str] = mapped_column(String(64))
    candle_close_ms: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GeminiAnalysis(Base):
    """One reservation per public snapshot. Never retry an ambiguous paid request."""
    __tablename__ = "gemini_analyses"
    request_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    model: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    thinking_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_nano_usd: Mapped[int] = mapped_column(Integer, default=0)
    usage_known: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class AiBudgetNotice(Base):
    __tablename__ = "ai_budget_notices"
    # Estimate and Cloud Billing are separate, explicitly labelled sources.
    notice_key: Mapped[str] = mapped_column(String(50), primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id"))
    cost_nano_usd: Mapped[int] = mapped_column(Integer)


def initialize_signal_tables(engine):
    Base.metadata.create_all(engine, tables=[TechnicalState.__table__, GeminiAnalysis.__table__,
                                            AiBudgetNotice.__table__], checkfirst=True)
