import datetime
import uuid

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mini import Base


class LLMUsageEvent(Base):
    """Individual LLM API call record for metering."""

    __tablename__ = "llm_usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    model: Mapped[str] = mapped_column(String(255))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserBudget(Base):
    """Per-user monthly spending budget and running total."""

    __tablename__ = "user_budgets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), unique=True)
    monthly_budget_usd: Mapped[float] = mapped_column(Float, default=5.0)
    total_spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    period_start: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GlobalBudget(Base):
    """Platform-wide spending threshold (singleton row, key='global')."""

    __tablename__ = "global_budget"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key: Mapped[str] = mapped_column(String(50), unique=True, default="global")
    monthly_budget_usd: Mapped[float] = mapped_column(Float, default=100.0)
    total_spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    period_start: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LLMUsageDaily(Base):
    """Daily aggregated LLM call counts keyed by (date, model_tier, user_id, endpoint).

    Upserted on every LLM call so totals stay current without a table scan.
    One row = one calendar day + tier + user + endpoint combination.
    """

    __tablename__ = "llm_usage_daily"
    __table_args__ = (
        UniqueConstraint("day", "model_tier", "user_id", "endpoint", name="uq_llm_usage_daily"),
        Index("ix_llm_usage_daily_day", "day"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    day: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    model_tier: Mapped[str] = mapped_column(String(50), nullable=False)
    # NULL means anonymous / no authenticated user
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    call_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
