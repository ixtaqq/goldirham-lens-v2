"""PostgreSQL schema. Every owner-specific row carries owner_id from the first migration."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
        Decimal: Numeric,
    }


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Owner(Base):
    __tablename__ = "owners"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    base_currency: Mapped[str] = mapped_column(String(3))
    timezone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()


class Preference(Base):
    __tablename__ = "preferences"
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), primary_key=True
    )
    risk_per_trade_pct: Mapped[Decimal | None]
    detail: Mapped[str | None] = mapped_column(String(16))
    alerts_mode: Mapped[str | None] = mapped_column(String(16))
    narrative_include_positions: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    updated_at: Mapped[datetime] = _now()
    __table_args__ = (
        CheckConstraint(
            "risk_per_trade_pct IS NULL OR (risk_per_trade_pct > 0 AND risk_per_trade_pct <= 5)",
            name="risk_range",
        ),
    )


class InstrumentRow(Base):
    __tablename__ = "instruments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    asset_class: Mapped[str] = mapped_column(String(8))
    market: Mapped[str] = mapped_column(String(12))
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = _now()
    __table_args__ = (
        CheckConstraint("asset_class IN ('crypto','stock','etf')", name="asset_class"),
    )


class WatchlistRow(Base):
    __tablename__ = "watchlist"
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), primary_key=True
    )
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    added_at: Mapped[datetime] = _now()


class BarRow(Base):
    __tablename__ = "bars"
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal]
    high: Mapped[Decimal]
    low: Mapped[Decimal]
    close: Mapped[Decimal]
    volume: Mapped[Decimal]
    provider: Mapped[str] = mapped_column(String(16))
    quality: Mapped[str] = mapped_column(String(32))
    reasons: Mapped[list[Any]] = mapped_column(server_default=text("'[]'::jsonb"))
    fetched_at: Mapped[datetime] = _now()
    __table_args__ = (
        CheckConstraint("low > 0 AND low <= high", name="price_range"),
        Index("ix_bars_day", "day"),
    )


class BarRevision(Base):
    __tablename__ = "bar_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    old_close: Mapped[Decimal]
    new_close: Mapped[Decimal]
    provider: Mapped[str] = mapped_column(String(16))
    detected_at: Mapped[datetime] = _now()


class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(16))
    ratio: Mapped[Decimal | None]
    source: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = _now()
    __table_args__ = (
        UniqueConstraint("instrument_id", "day", "kind", name="uq_corporate_actions_key"),
    )


class FxRateRow(Base):
    __tablename__ = "fx_rates"
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    quote: Mapped[str] = mapped_column(String(3), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    rate: Mapped[Decimal]
    source: Mapped[str] = mapped_column(String(16))
    fetched_at: Mapped[datetime] = _now()
    __table_args__ = (CheckConstraint("rate > 0", name="positive"),)


class FundamentalsRow(Base):
    __tablename__ = "fundamentals"
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True
    )
    pe_ratio: Mapped[Decimal | None]
    revenue_growth_pct: Mapped[Decimal | None]
    as_of: Mapped[date] = mapped_column(Date)
    fetched_at: Mapped[datetime] = _now()


class StrategyVersionRow(Base):
    __tablename__ = "strategy_versions"
    version: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict[str, Any]]
    code_version: Mapped[str] = mapped_column(String(8))
    report_id: Mapped[int | None] = mapped_column(ForeignKey("backtest_reports.id"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class BacktestReportRow(Base):
    __tablename__ = "backtest_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_version: Mapped[str] = mapped_column(String(12), index=True)
    name: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict[str, Any]]
    from_day: Mapped[date] = mapped_column(Date)
    to_day: Mapped[date] = mapped_column(Date)
    report: Mapped[dict[str, Any]]
    report_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"))
    briefing_date: Mapped[date] = mapped_column(Date)
    trigger: Mapped[str] = mapped_column(String(24))
    github_run_id: Mapped[str | None] = mapped_column(String(32))
    code_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16))
    error_class: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StageRun(Base):
    __tablename__ = "stage_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(24))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(16))
    error_class: Mapped[str | None] = mapped_column(String(80))


class DailyCycle(Base):
    """The once-per-day lock. A second trigger reads this row and exits."""

    __tablename__ = "daily_cycles"
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), primary_key=True
    )
    briefing_date: Mapped[date] = mapped_column(Date, primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
    claim_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    updated_at: Mapped[datetime] = _now()
    __table_args__ = (CheckConstraint("state IN ('RUNNING','DONE','FAILED')", name="state"),)


class BriefingRow(Base):
    __tablename__ = "briefings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"))
    briefing_date: Mapped[date] = mapped_column(Date)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    mode: Mapped[str] = mapped_column(String(16))
    document: Mapped[dict[str, Any]]
    chunks: Mapped[list[Any]]
    inputs: Mapped[dict[str, Any]]
    code_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("owner_id", "briefing_date", name="uq_briefings_owner_day"),)


class DeliveryRow(Base):
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    briefing_id: Mapped[int] = mapped_column(
        ForeignKey("briefings.id", ondelete="CASCADE"), unique=True
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"))
    briefing_date: Mapped[date] = mapped_column(Date)
    state: Mapped[str] = mapped_column(String(16))
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    message_ids: Mapped[list[Any]] = mapped_column(server_default=text("'[]'::jsonb"))
    error_class: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = _now()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    held_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(String(16))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("owner_id", "briefing_date", name="uq_deliveries_owner_day"),
        CheckConstraint(
            "state IN ('COMPOSED','CLAIMED','SENDING','SENT','HELD','FAILED','RESENT','DISMISSED')",
            name="state",
        ),
    )


class DecisionRow(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"))
    session: Mapped[date] = mapped_column(Date)
    strategy: Mapped[str] = mapped_column(String(40))
    strategy_version: Mapped[str] = mapped_column(String(12))
    eligible: Mapped[bool]
    reasons: Mapped[list[Any]]
    indicators: Mapped[dict[str, Any]]
    setup: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    readiness: Mapped[list[Any]] = mapped_column(server_default=text("'[]'::jsonb"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    created_at: Mapped[datetime] = _now()
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "instrument_id", "session", "strategy_version", name="uq_decisions_key"
        ),
        Index("ix_decisions_lookup", "owner_id", "instrument_id", "session"),
    )


class SignalRow(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"))
    strategy: Mapped[str] = mapped_column(String(40))
    strategy_version: Mapped[str] = mapped_column(String(12))
    signal_day: Mapped[date] = mapped_column(Date)
    entry: Mapped[Decimal]
    stop: Mapped[Decimal]
    t1: Mapped[Decimal]
    t2: Mapped[Decimal]
    size_pct: Mapped[Decimal]
    expiry_days: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'OPEN'"))
    last_evaluated: Mapped[date | None] = mapped_column(Date)
    t1_touched_on: Mapped[date | None] = mapped_column(Date)
    exit_day: Mapped[date | None] = mapped_column(Date)
    exit_price: Mapped[Decimal | None]
    outcome_r: Mapped[Decimal | None]
    outcome_r_scaled: Mapped[Decimal | None]
    mfe_r: Mapped[Decimal] = mapped_column(server_default=text("0"))
    mae_r: Mapped[Decimal] = mapped_column(server_default=text("0"))
    last_close: Mapped[Decimal | None]
    created_at: Mapped[datetime] = _now()
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "instrument_id", "strategy_version", "signal_day", name="uq_signals_key"
        ),
        CheckConstraint("stop < entry AND entry < t1 AND t1 < t2", name="ordered_levels"),
        CheckConstraint(
            "status IN ('OPEN','STOPPED','T2_HIT','EXPIRED','UNVERIFIABLE')", name="status"
        ),
        Index("ix_signals_open", "owner_id", postgresql_where=text("status = 'OPEN'")),
    )


class SignalEventRow(Base):
    __tablename__ = "signal_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24))
    day: Mapped[date] = mapped_column(Date)
    price: Mapped[Decimal | None]
    r: Mapped[Decimal | None]
    created_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("signal_id", "kind", "day", name="uq_signal_events_key"),)


class TransactionRow(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    kind: Mapped[str] = mapped_column(String(16))
    day: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    quantity: Mapped[Decimal] = mapped_column(server_default=text("0"))
    price: Mapped[Decimal] = mapped_column(server_default=text("0"))
    fee: Mapped[Decimal] = mapped_column(server_default=text("0"))
    amount: Mapped[Decimal] = mapped_column(server_default=text("0"))
    ratio: Mapped[Decimal] = mapped_column(server_default=text("0"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (
        CheckConstraint(
            "kind IN ('BUY','SELL','FEE','DIVIDEND','SPLIT','TRANSFER_IN','TRANSFER_OUT')",
            name="kind",
        ),
        CheckConstraint("quantity >= 0 AND price >= 0 AND fee >= 0", name="non_negative"),
    )


class ThesisNote(Base):
    __tablename__ = "thesis_notes"
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), primary_key=True
    )
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    note: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = _now()


class HoldingReviewRow(Base):
    __tablename__ = "holding_reviews"
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), primary_key=True
    )
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    session: Mapped[date] = mapped_column(Date, primary_key=True)
    action: Mapped[str] = mapped_column(String(8))
    reasons: Mapped[list[Any]]
    created_at: Mapped[datetime] = _now()


class AlertRow(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    kind: Mapped[str] = mapped_column(String(32))
    session: Mapped[date] = mapped_column(Date)
    state: Mapped[str] = mapped_column(String(12), server_default=text("'PENDING'"))
    created_at: Mapped[datetime] = _now()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("owner_id", "instrument_id", "kind", "session", name="uq_alerts_key"),
    )


class LevelAlertRow(Base):
    """A price level the owner set. It fires once, on the first completed close that crosses it."""

    __tablename__ = "level_alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    direction: Mapped[str] = mapped_column(String(5))
    level: Mapped[Decimal]
    created_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = _now()
    triggered_on: Mapped[date | None] = mapped_column(Date)
    triggered_close: Mapped[Decimal | None]
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("direction IN ('above','below')", name="direction"),)


class AiUsage(Base):
    __tablename__ = "ai_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"))
    utc_date: Mapped[date] = mapped_column(Date)
    model: Mapped[str] = mapped_column(String(48))
    reserved_usd: Mapped[Decimal]
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None]
    status: Mapped[str] = mapped_column(String(12))
    error_class: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = _now()
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('RESERVED','SETTLED','FAILED','UNKNOWN')", name="status"),
        Index("ix_ai_usage_day", "owner_id", "utc_date"),
    )


class OperationalEvent(Base):
    __tablename__ = "operational_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(12))
    source: Mapped[str] = mapped_column(String(48))
    details: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    dedupe_key: Mapped[str] = mapped_column(String(120), unique=True)
    occurred_at: Mapped[datetime] = _now()
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FeedbackRow(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"))
    briefing_id: Mapped[int] = mapped_column(ForeignKey("briefings.id", ondelete="CASCADE"))
    rating: Mapped[str] = mapped_column(String(8))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (
        UniqueConstraint("owner_id", "briefing_id", name="uq_feedback_key"),
        CheckConstraint("rating IN ('useful','quiet','noisy')", name="rating"),
    )


class ProviderCallRow(Base):
    __tablename__ = "provider_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(24))
    ok: Mapped[bool]
    latency_ms: Mapped[int] = mapped_column(Integer)
    error_class: Mapped[str | None] = mapped_column(String(80))
    at: Mapped[datetime] = _now()
    __table_args__ = (Index("ix_provider_calls_at", "provider", "at"),)


class PendingAction(Base):
    """A confirmation the owner taps once: a ledger entry or a held-briefing resend."""

    __tablename__ = "pending_actions"
    token: Mapped[str] = mapped_column(String(24), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24))
    payload: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
