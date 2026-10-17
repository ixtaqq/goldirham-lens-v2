"""Operational events, AI budget ledger, feedback, preferences, alerts and one-tap confirmations."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lens.storage.models import (
    AiUsage,
    AlertRow,
    FeedbackRow,
    OperationalEvent,
    PendingAction,
    Preference,
    ProviderCallRow,
)


@dataclass(frozen=True, slots=True)
class UsageSummary:
    calls: int
    committed_usd: Decimal
    unknown: int


@dataclass(frozen=True, slots=True)
class Preferences:
    risk_per_trade_pct: Decimal | None
    detail: str | None
    alerts_mode: str | None
    narrative_include_positions: bool


class OpsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def record_event(
        self,
        *,
        kind: str,
        severity: str,
        source: str,
        dedupe_key: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """Record once per dedupe key. Returns True only the first time, so alerts fire once."""
        inserted = await self.s.scalar(
            insert(OperationalEvent)
            .values(
                kind=kind,
                severity=severity,
                source=source,
                dedupe_key=dedupe_key,
                details=details or {},
            )
            .on_conflict_do_nothing(index_elements=[OperationalEvent.dedupe_key])
            .returning(OperationalEvent.id)
        )
        return inserted is not None

    # ------------------------------------------------------------------ AI budget

    async def usage(self, owner_id: int, day: date) -> UsageSummary:
        rows = (
            await self.s.execute(
                select(AiUsage.status, AiUsage.reserved_usd, AiUsage.cost_usd).where(
                    AiUsage.owner_id == owner_id, AiUsage.utc_date == day
                )
            )
        ).all()
        committed = Decimal(0)
        unknown = 0
        for status, reserved, cost in rows:
            if status in ("RESERVED", "UNKNOWN"):
                committed += reserved
                unknown += status == "UNKNOWN"
            elif cost is not None:
                committed += cost
        return UsageSummary(len(rows), committed, unknown)

    async def reserve_ai(
        self,
        *,
        owner_id: int,
        day: date,
        model: str,
        amount: Decimal,
        max_calls: int,
        budget_usd: Decimal,
    ) -> int | None:
        """Atomically reserve `amount` against today's limits. None means the budget says no."""
        await self.s.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"ai:{owner_id}:{day.isoformat()}"},
        )
        summary = await self.usage(owner_id, day)
        if summary.calls >= max_calls or summary.committed_usd + amount > budget_usd:
            return None
        reservation = await self.s.scalar(
            insert(AiUsage)
            .values(
                owner_id=owner_id, utc_date=day, model=model, reserved_usd=amount, status="RESERVED"
            )
            .returning(AiUsage.id)
        )
        assert reservation is not None
        return int(reservation)

    async def settle_ai(
        self,
        reservation_id: int,
        *,
        status: str,
        now: datetime,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: Decimal | None = None,
        error_class: str | None = None,
    ) -> None:
        await self.s.execute(
            update(AiUsage)
            .where(AiUsage.id == reservation_id, AiUsage.status == "RESERVED")
            .values(
                status=status,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                error_class=error_class,
                settled_at=now,
            )
        )

    # ------------------------------------------------------------------ preferences and feedback

    async def preferences(self, owner_id: int) -> Preferences:
        row = await self.s.get(Preference, owner_id)
        if row is None:
            return Preferences(None, None, None, False)
        return Preferences(
            row.risk_per_trade_pct, row.detail, row.alerts_mode, row.narrative_include_positions
        )

    async def set_preference(self, owner_id: int, **values: Any) -> None:
        statement = insert(Preference).values(owner_id=owner_id, **values)
        await self.s.execute(
            statement.on_conflict_do_update(index_elements=[Preference.owner_id], set_=values)
        )

    async def save_feedback(
        self, owner_id: int, briefing_id: int, rating: str, note: str | None
    ) -> None:
        statement = insert(FeedbackRow).values(
            owner_id=owner_id, briefing_id=briefing_id, rating=rating, note=note
        )
        await self.s.execute(
            statement.on_conflict_do_update(
                constraint="uq_feedback_key", set_={"rating": rating, "note": note}
            )
        )

    # ------------------------------------------------------------------ alerts

    async def claim_alert(
        self, owner_id: int, instrument_id: int, kind: str, session: date
    ) -> bool:
        """True only for the first claim of this (asset, kind, session): one alert per episode."""
        inserted = await self.s.scalar(
            insert(AlertRow)
            .values(owner_id=owner_id, instrument_id=instrument_id, kind=kind, session=session)
            .on_conflict_do_nothing(constraint="uq_alerts_key")
            .returning(AlertRow.id)
        )
        return inserted is not None

    # ------------------------------------------------------------------ one-tap confirmations

    async def create_action(
        self,
        owner_id: int,
        kind: str,
        payload: dict[str, Any],
        now: datetime,
        ttl: timedelta = timedelta(minutes=15),
    ) -> str:
        token = secrets.token_urlsafe(12)
        self.s.add(
            PendingAction(
                token=token, owner_id=owner_id, kind=kind, payload=payload, expires_at=now + ttl
            )
        )
        await self.s.flush()
        return token

    async def consume_action(
        self, token: str, owner_id: int, now: datetime
    ) -> tuple[str, dict[str, Any]] | None:
        """Use a confirmation exactly once. A second tap, or a tap after expiry, gets None."""
        row = await self.s.execute(
            update(PendingAction)
            .where(
                PendingAction.token == token,
                PendingAction.owner_id == owner_id,
                PendingAction.consumed_at.is_(None),
                PendingAction.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(PendingAction.kind, PendingAction.payload)
        )
        found = row.first()
        return None if found is None else (found[0], found[1])

    # ------------------------------------------------------------------ provider health

    async def provider_health(self, since: datetime) -> list[tuple[str, int, int, int | None]]:
        """(provider, calls, failures, p95 latency ms) since `since`."""
        rows = await self.s.execute(
            select(
                ProviderCallRow.provider,
                func.count(),
                func.count().filter(ProviderCallRow.ok.is_(False)),
                func.percentile_cont(0.95).within_group(ProviderCallRow.latency_ms),
            )
            .where(ProviderCallRow.at >= since)
            .group_by(ProviderCallRow.provider)
            .order_by(ProviderCallRow.provider)
        )
        return [(p, int(c), int(f), None if q is None else int(q)) for p, c, f, q in rows.all()]
