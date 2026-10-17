"""Decisions, signals, signal events and holding reviews."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lens.domain.evaluation import Event, Levels, SignalState, SignalStatus
from lens.domain.holdings import HoldingReview, ReviewAction
from lens.domain.reasons import ReasonCode
from lens.domain.scorecard import SignalRecord
from lens.domain.strategy.base import Decision
from lens.storage.models import (
    DecisionRow,
    HoldingReviewRow,
    InstrumentRow,
    SignalEventRow,
    SignalRow,
)


@dataclass(frozen=True, slots=True)
class OpenSignal:
    id: int
    symbol: str
    strategy: str
    signal_day: date
    expiry_days: int
    levels: Levels
    state: SignalState


@dataclass(frozen=True, slots=True)
class StoredDecision:
    symbol: str
    session: date
    strategy: str
    strategy_version: str
    eligible: bool
    reasons: tuple[ReasonCode, ...]
    readiness: tuple[ReasonCode, ...]
    indicators: dict[str, Any]
    setup: dict[str, Any] | None


def setup_json(decision: Decision) -> dict[str, Any] | None:
    s = decision.setup
    if s is None:
        return None
    return {
        "entry": str(s.entry),
        "stop": str(s.stop),
        "t1": str(s.t1),
        "t2": str(s.t2),
        "reward_risk": str(s.reward_risk),
        "size_pct": str(s.size_pct),
        "size_capped": s.size_capped,
        "method": s.method,
    }


class SignalRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def save_decision(
        self,
        owner_id: int,
        instrument_id: int,
        decision: Decision,
        readiness: tuple[ReasonCode, ...],
        run_id: int | None,
    ) -> None:
        values = {
            "eligible": decision.eligible,
            "reasons": [r.value for r in decision.reasons],
            "readiness": [r.value for r in readiness],
            "indicators": dict(decision.indicators.items()),
            "setup": setup_json(decision),
            "run_id": run_id,
            "strategy": decision.strategy,
        }
        statement = insert(DecisionRow).values(
            owner_id=owner_id,
            instrument_id=instrument_id,
            session=decision.session,
            strategy_version=decision.strategy_version,
            **values,
        )
        await self.s.execute(
            statement.on_conflict_do_update(constraint="uq_decisions_key", set_=values)
        )

    async def latest_decisions(self, owner_id: int, symbol: str) -> list[StoredDecision]:
        latest = (
            select(DecisionRow.session)
            .join(InstrumentRow, InstrumentRow.id == DecisionRow.instrument_id)
            .where(DecisionRow.owner_id == owner_id, InstrumentRow.symbol == symbol)
            .order_by(DecisionRow.session.desc())
            .limit(1)
            .scalar_subquery()
        )
        rows = await self.s.scalars(
            select(DecisionRow)
            .join(InstrumentRow, InstrumentRow.id == DecisionRow.instrument_id)
            .where(
                DecisionRow.owner_id == owner_id,
                InstrumentRow.symbol == symbol,
                DecisionRow.session == latest,
            )
            .order_by(DecisionRow.strategy)
        )
        return [
            StoredDecision(
                symbol,
                r.session,
                r.strategy,
                r.strategy_version,
                r.eligible,
                tuple(ReasonCode(x) for x in r.reasons),
                tuple(ReasonCode(x) for x in r.readiness),
                r.indicators,
                r.setup,
            )
            for r in rows
        ]

    async def create_signal(
        self, owner_id: int, instrument_id: int, decision: Decision, expiry_days: int
    ) -> bool:
        setup = decision.setup
        assert setup is not None
        created = await self.s.scalar(
            insert(SignalRow)
            .values(
                owner_id=owner_id,
                instrument_id=instrument_id,
                strategy=decision.strategy,
                strategy_version=decision.strategy_version,
                signal_day=decision.session,
                entry=setup.entry,
                stop=setup.stop,
                t1=setup.t1,
                t2=setup.t2,
                size_pct=setup.size_pct,
                expiry_days=expiry_days,
            )
            .on_conflict_do_nothing(constraint="uq_signals_key")
            .returning(SignalRow.id)
        )
        return created is not None

    async def open_signals(self, owner_id: int) -> list[OpenSignal]:
        rows = await self.s.execute(
            select(SignalRow, InstrumentRow.symbol)
            .join(InstrumentRow, InstrumentRow.id == SignalRow.instrument_id)
            .where(SignalRow.owner_id == owner_id, SignalRow.status == SignalStatus.OPEN.value)
            .order_by(SignalRow.signal_day)
        )
        return [
            OpenSignal(
                row.id,
                symbol,
                row.strategy,
                row.signal_day,
                row.expiry_days,
                Levels(row.entry, row.stop, row.t1, row.t2),
                SignalState(
                    SignalStatus(row.status),
                    row.last_evaluated,
                    row.t1_touched_on,
                    row.exit_day,
                    row.exit_price,
                    row.outcome_r,
                    row.outcome_r_scaled,
                    row.mfe_r,
                    row.mae_r,
                    row.last_close,
                ),
            )
            for row, symbol in rows.all()
        ]

    async def apply_state(self, signal_id: int, state: SignalState, events: list[Event]) -> None:
        row = await self.s.get(SignalRow, signal_id, with_for_update=True)
        assert row is not None
        if row.status != SignalStatus.OPEN.value:
            return
        row.status = state.status.value
        row.last_evaluated = state.last_evaluated
        row.t1_touched_on = state.t1_touched_on
        row.exit_day = state.exit_day
        row.exit_price = state.exit_price
        row.outcome_r = state.outcome_r
        row.outcome_r_scaled = state.outcome_r_scaled
        row.mfe_r = state.mfe_r
        row.mae_r = state.mae_r
        row.last_close = state.last_close
        if events:
            await self.s.execute(
                insert(SignalEventRow)
                .values(
                    [
                        {
                            "signal_id": signal_id,
                            "kind": e.kind.value,
                            "day": e.day,
                            "price": e.price,
                            "r": e.r,
                        }
                        for e in events
                    ]
                )
                .on_conflict_do_nothing()
            )

    async def records(self, owner_id: int) -> list[SignalRecord]:
        rows = await self.s.scalars(select(SignalRow).where(SignalRow.owner_id == owner_id))
        return [
            SignalRecord(
                r.signal_day,
                SignalStatus(r.status),
                r.t1_touched_on is not None,
                r.outcome_r,
                r.outcome_r_scaled,
                r.exit_day,
                r.mfe_r,
                r.mae_r,
            )
            for r in rows
        ]

    async def save_review(
        self, owner_id: int, instrument_id: int, session: date, review: HoldingReview
    ) -> None:
        values = {"action": review.action.value, "reasons": [r.value for r in review.reasons]}
        statement = insert(HoldingReviewRow).values(
            owner_id=owner_id, instrument_id=instrument_id, session=session, **values
        )
        await self.s.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    HoldingReviewRow.owner_id,
                    HoldingReviewRow.instrument_id,
                    HoldingReviewRow.session,
                ],
                set_=values,
            )
        )

    async def previous_reviews(self, owner_id: int, before: date) -> dict[str, ReviewAction]:
        rows = await self.s.execute(
            select(InstrumentRow.symbol, HoldingReviewRow.action, HoldingReviewRow.session)
            .join(InstrumentRow, InstrumentRow.id == HoldingReviewRow.instrument_id)
            .where(HoldingReviewRow.owner_id == owner_id, HoldingReviewRow.session < before)
            .order_by(HoldingReviewRow.session)
        )
        latest: dict[str, ReviewAction] = {}
        for symbol, action, _ in rows.all():
            latest[symbol] = ReviewAction(action)
        return latest
