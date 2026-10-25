"""Read-only queries behind the dashboard views. Every owner-specific query filters by owner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lens.storage.models import (
    AiUsage,
    BacktestReportRow,
    BriefingRow,
    DeliveryRow,
    InstrumentRow,
    OperationalEvent,
    PipelineRun,
    SignalEventRow,
    SignalRow,
    StageRun,
    StrategyVersionRow,
)


@dataclass(frozen=True, slots=True)
class BriefingSummary:
    day: date
    mode: str
    delivery: str | None
    sent_at: datetime | None
    messages: int


@dataclass(frozen=True, slots=True)
class BriefingDetail:
    day: date
    mode: str
    chunks: list[str]
    delivery: str | None
    resolution: str | None


@dataclass(frozen=True, slots=True)
class PortfolioPoint:
    day: date
    total: Decimal
    currency: str
    exposure: dict[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SignalSummary:
    id: int
    symbol: str
    currency: str
    strategy: str
    version: str
    signal_day: date
    status: str
    entry: Decimal
    stop: Decimal
    t1: Decimal
    t2: Decimal
    exit_day: date | None
    outcome_r: Decimal | None


@dataclass(frozen=True, slots=True)
class SignalEvent:
    kind: str
    day: date
    price: Decimal | None
    r: Decimal | None


@dataclass(frozen=True, slots=True)
class ReportSummary:
    id: int
    name: str
    version: str
    from_day: date
    to_day: date
    report_hash: str
    active: bool


@dataclass(frozen=True, slots=True)
class ReportDetail:
    summary: ReportSummary
    body: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RunSummary:
    id: int
    briefing_date: date
    trigger: str
    status: str
    error_class: str | None
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class StageSummary:
    stage: str
    outcome: str
    seconds: float
    error_class: str | None


@dataclass(frozen=True, slots=True)
class EventSummary:
    kind: str
    severity: str
    source: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class Health:
    runs: list[RunSummary]
    stages: list[StageSummary]
    deliveries: list[tuple[date, str]]
    events: list[EventSummary]
    ai_spend_7d: Decimal


async def briefings(session: AsyncSession, owner_id: int, limit: int = 90) -> list[BriefingSummary]:
    rows = await session.execute(
        select(BriefingRow, DeliveryRow.state, DeliveryRow.sent_at)
        .outerjoin(DeliveryRow, DeliveryRow.briefing_id == BriefingRow.id)
        .where(BriefingRow.owner_id == owner_id)
        .order_by(BriefingRow.briefing_date.desc(), BriefingRow.id.desc())
        .limit(limit)
    )
    seen: set[date] = set()
    result = []
    for briefing, state, sent_at in rows:
        if briefing.briefing_date in seen:
            continue
        seen.add(briefing.briefing_date)
        result.append(
            BriefingSummary(
                briefing.briefing_date, briefing.mode, state, sent_at, len(briefing.chunks)
            )
        )
    return result


async def briefing(session: AsyncSession, owner_id: int, day: date) -> BriefingDetail | None:
    row = (
        await session.execute(
            select(BriefingRow, DeliveryRow.state, DeliveryRow.resolution)
            .outerjoin(DeliveryRow, DeliveryRow.briefing_id == BriefingRow.id)
            .where(BriefingRow.owner_id == owner_id, BriefingRow.briefing_date == day)
            .order_by(BriefingRow.id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    found, state, resolution = row
    return BriefingDetail(
        found.briefing_date, found.mode, [str(c) for c in found.chunks], state, resolution
    )


async def portfolio_history(
    session: AsyncSession, owner_id: int, limit: int = 400
) -> list[PortfolioPoint]:
    rows = await session.execute(
        select(BriefingRow.briefing_date, BriefingRow.document)
        .where(BriefingRow.owner_id == owner_id)
        .order_by(BriefingRow.briefing_date.desc(), BriefingRow.id.desc())
        .limit(limit)
    )
    points: dict[date, PortfolioPoint] = {}
    for day, document in rows:
        portfolio = (document or {}).get("portfolio")
        if day in points or not portfolio:
            continue
        points[day] = PortfolioPoint(
            day,
            Decimal(str(portfolio["total_base"])),
            str(portfolio["base_currency"]),
            {
                str(k): Decimal(str(v))
                for k, v in (portfolio.get("exposure_by_asset_class") or {}).items()
            },
        )
    return sorted(points.values(), key=lambda p: p.day)


def _signal(row: SignalRow, symbol: str, currency: str) -> SignalSummary:
    return SignalSummary(
        row.id,
        symbol,
        currency,
        row.strategy,
        row.strategy_version,
        row.signal_day,
        row.status,
        row.entry,
        row.stop,
        row.t1,
        row.t2,
        row.exit_day,
        row.outcome_r,
    )


async def signals(
    session: AsyncSession, owner_id: int, *, status: str | None = None, symbol: str | None = None
) -> list[SignalSummary]:
    query = (
        select(SignalRow, InstrumentRow.symbol, InstrumentRow.currency)
        .join(InstrumentRow, InstrumentRow.id == SignalRow.instrument_id)
        .where(SignalRow.owner_id == owner_id)
        .order_by(SignalRow.signal_day.desc(), SignalRow.id.desc())
        .limit(500)
    )
    if status:
        query = query.where(SignalRow.status == status)
    if symbol:
        query = query.where(InstrumentRow.symbol == symbol.upper())
    return [_signal(row, sym, cur) for row, sym, cur in await session.execute(query)]


async def signal(
    session: AsyncSession, owner_id: int, signal_id: int
) -> tuple[SignalSummary, list[SignalEvent]] | None:
    row = (
        await session.execute(
            select(SignalRow, InstrumentRow.symbol, InstrumentRow.currency)
            .join(InstrumentRow, InstrumentRow.id == SignalRow.instrument_id)
            .where(SignalRow.owner_id == owner_id, SignalRow.id == signal_id)
        )
    ).first()
    if row is None:
        return None
    events = await session.execute(
        select(SignalEventRow)
        .where(SignalEventRow.signal_id == signal_id)
        .order_by(SignalEventRow.day, SignalEventRow.id)
    )
    return _signal(*row), [SignalEvent(e.kind, e.day, e.price, e.r) for e in events.scalars()]


async def _active_versions(session: AsyncSession) -> set[str]:
    rows = await session.execute(
        select(StrategyVersionRow.version).where(StrategyVersionRow.activated_at.is_not(None))
    )
    return set(rows.scalars())


def _report(row: BacktestReportRow, active: set[str]) -> ReportSummary:
    return ReportSummary(
        row.id,
        row.name,
        row.strategy_version,
        row.from_day,
        row.to_day,
        row.report_hash,
        row.strategy_version in active,
    )


async def reports(session: AsyncSession) -> list[ReportSummary]:
    active = await _active_versions(session)
    rows = await session.execute(
        select(BacktestReportRow).order_by(BacktestReportRow.created_at.desc())
    )
    return [_report(row, active) for row in rows.scalars()]


async def report(session: AsyncSession, report_id: int) -> ReportDetail | None:
    row = await session.get(BacktestReportRow, report_id)
    if row is None:
        return None
    return ReportDetail(_report(row, await _active_versions(session)), row.report)


async def health(session: AsyncSession, owner_id: int, now: datetime | None = None) -> Health:
    now = now or datetime.now(UTC)
    runs = [
        RunSummary(
            r.id, r.briefing_date, r.trigger, r.status, r.error_class, r.started_at, r.finished_at
        )
        for r in (
            await session.execute(
                select(PipelineRun)
                .where(PipelineRun.owner_id == owner_id)
                .order_by(PipelineRun.started_at.desc())
                .limit(14)
            )
        ).scalars()
    ]
    stages: list[StageSummary] = []
    if runs:
        for s in (
            await session.execute(
                select(StageRun).where(StageRun.run_id == runs[0].id).order_by(StageRun.started_at)
            )
        ).scalars():
            seconds = (s.finished_at - s.started_at).total_seconds()
            stages.append(StageSummary(s.stage, s.outcome, seconds, s.error_class))
    deliveries = [
        (day, state)
        for day, state in await session.execute(
            select(DeliveryRow.briefing_date, DeliveryRow.state)
            .where(DeliveryRow.owner_id == owner_id)
            .order_by(DeliveryRow.briefing_date.desc())
            .limit(14)
        )
    ]
    events = [
        EventSummary(e.kind, e.severity, e.source, e.occurred_at)
        for e in (
            await session.execute(
                select(OperationalEvent).order_by(OperationalEvent.occurred_at.desc()).limit(20)
            )
        ).scalars()
    ]
    spend = await session.scalar(
        select(
            func.coalesce(func.sum(func.coalesce(AiUsage.cost_usd, AiUsage.reserved_usd)), 0)
        ).where(AiUsage.owner_id == owner_id, AiUsage.utc_date >= (now - timedelta(days=7)).date())
    )
    return Health(runs, stages, deliveries, events, Decimal(str(spend or 0)))
