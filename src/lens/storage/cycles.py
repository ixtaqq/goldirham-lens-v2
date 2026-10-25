"""The daily claim, run records, stored briefings, and the delivery state machine's rows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lens.storage.models import (
    BriefingRow,
    DailyCycle,
    DeliveryRow,
    PipelineRun,
    ProviderCallRow,
    StageRun,
)

STALE_CLAIM = timedelta(minutes=20)
STALE_SENDING = timedelta(minutes=10)


class ClaimOutcome(StrEnum):
    CLAIMED = "claimed"
    ALREADY_DONE = "already_done"
    IN_PROGRESS = "in_progress"


@dataclass(frozen=True, slots=True)
class Claim:
    outcome: ClaimOutcome
    token: uuid.UUID | None


class DeliveryState(StrEnum):
    COMPOSED = "COMPOSED"
    CLAIMED = "CLAIMED"
    SENDING = "SENDING"
    SENT = "SENT"
    HELD = "HELD"
    FAILED = "FAILED"
    RESENT = "RESENT"
    DISMISSED = "DISMISSED"


DELIVERED = frozenset(
    {DeliveryState.SENT, DeliveryState.HELD, DeliveryState.RESENT, DeliveryState.DISMISSED}
)


@dataclass(frozen=True, slots=True)
class StoredBriefing:
    id: int
    owner_id: int
    briefing_date: date
    mode: str
    document: dict[str, Any]
    chunks: list[str]
    inputs: dict[str, Any]
    code_version: str
    delivery_state: DeliveryState | None
    delivery_id: int | None
    message_ids: list[int | None]


class CycleRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def claim_day(self, owner_id: int, day: date, now: datetime) -> Claim:
        """Take the once-per-day lock, or report who holds it. Stale RUNNING claims are adopted."""
        token = uuid.uuid4()
        inserted = await self.s.scalar(
            insert(DailyCycle)
            .values(
                owner_id=owner_id,
                briefing_date=day,
                state="RUNNING",
                claim_token=token,
                claimed_at=now,
            )
            .on_conflict_do_nothing()
            .returning(DailyCycle.claim_token)
        )
        if inserted is not None:
            return Claim(ClaimOutcome.CLAIMED, token)
        row = await self.s.scalar(
            select(DailyCycle)
            .where(DailyCycle.owner_id == owner_id, DailyCycle.briefing_date == day)
            .with_for_update()
        )
        assert row is not None
        if row.state == "DONE":
            return Claim(ClaimOutcome.ALREADY_DONE, None)
        if row.state == "RUNNING" and now - row.claimed_at < STALE_CLAIM:
            return Claim(ClaimOutcome.IN_PROGRESS, None)
        row.state, row.claim_token, row.claimed_at, row.updated_at = "RUNNING", token, now, now
        return Claim(ClaimOutcome.CLAIMED, token)

    async def release_day(
        self, owner_id: int, day: date, token: uuid.UUID, state: str, now: datetime
    ) -> bool:
        result = await self.s.execute(
            update(DailyCycle)
            .where(
                DailyCycle.owner_id == owner_id,
                DailyCycle.briefing_date == day,
                DailyCycle.claim_token == token,
            )
            .values(state=state, updated_at=now)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def start_run(
        self,
        *,
        cycle_id: uuid.UUID,
        owner_id: int,
        day: date,
        trigger: str,
        github_run_id: str | None,
        code_version: str,
        now: datetime,
    ) -> int:
        run_id = await self.s.scalar(
            insert(PipelineRun)
            .values(
                cycle_id=cycle_id,
                owner_id=owner_id,
                briefing_date=day,
                trigger=trigger,
                github_run_id=github_run_id,
                code_version=code_version,
                status="RUNNING",
                started_at=now,
            )
            .returning(PipelineRun.id)
        )
        assert run_id is not None
        return int(run_id)

    async def finish_run(
        self, run_id: int, status: str, now: datetime, error_class: str | None = None
    ) -> None:
        await self.s.execute(
            update(PipelineRun)
            .where(PipelineRun.id == run_id)
            .values(status=status, finished_at=now, error_class=error_class)
        )

    async def record_stage(
        self,
        run_id: int,
        stage: str,
        started: datetime,
        finished: datetime,
        outcome: str,
        error_class: str | None = None,
    ) -> None:
        self.s.add(
            StageRun(
                run_id=run_id,
                stage=stage,
                started_at=started,
                finished_at=finished,
                outcome=outcome,
                error_class=error_class,
            )
        )

    async def record_provider_calls(
        self, run_id: int | None, calls: list[tuple[str, bool, int, str | None]]
    ) -> None:
        if calls:
            await self.s.execute(
                insert(ProviderCallRow).values(
                    [
                        {
                            "run_id": run_id,
                            "provider": p,
                            "ok": ok,
                            "latency_ms": ms,
                            "error_class": e,
                        }
                        for p, ok, ms, e in calls
                    ]
                )
            )

    async def save_briefing(
        self,
        *,
        owner_id: int,
        day: date,
        run_id: int | None,
        mode: str,
        document: dict[str, Any],
        chunks: list[str],
        inputs: dict[str, Any],
        code_version: str,
    ) -> StoredBriefing:
        """Store today's briefing and its COMPOSED delivery. A delivered briefing is never replaced."""
        existing = await self.briefing_on(owner_id, day)
        if existing is not None and existing.delivery_state in DELIVERED | {
            DeliveryState.SENDING,
            DeliveryState.CLAIMED,
        }:
            return existing
        values = {
            "run_id": run_id,
            "mode": mode,
            "document": document,
            "chunks": chunks,
            "inputs": inputs,
            "code_version": code_version,
        }
        statement = insert(BriefingRow).values(owner_id=owner_id, briefing_date=day, **values)
        briefing_id = await self.s.scalar(
            statement.on_conflict_do_update(
                constraint="uq_briefings_owner_day", set_=values
            ).returning(BriefingRow.id)
        )
        assert briefing_id is not None
        delivery = insert(DeliveryRow).values(
            briefing_id=briefing_id,
            owner_id=owner_id,
            briefing_date=day,
            state=DeliveryState.COMPOSED.value,
            message_ids=[None] * len(chunks),
        )
        await self.s.execute(
            delivery.on_conflict_do_update(
                index_elements=[DeliveryRow.briefing_id],
                set_={
                    "state": DeliveryState.COMPOSED.value,
                    "message_ids": [None] * len(chunks),
                    "error_class": None,
                },
            )
        )
        stored = await self.briefing_on(owner_id, day)
        assert stored is not None
        return stored

    async def _load(self, condition: Any) -> StoredBriefing | None:
        row = (
            await self.s.execute(
                select(BriefingRow, DeliveryRow)
                .outerjoin(DeliveryRow, DeliveryRow.briefing_id == BriefingRow.id)
                .where(condition)
                .order_by(BriefingRow.briefing_date.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            return None
        briefing, delivery = row
        return StoredBriefing(
            briefing.id,
            briefing.owner_id,
            briefing.briefing_date,
            briefing.mode,
            briefing.document,
            list(briefing.chunks),
            briefing.inputs,
            briefing.code_version,
            DeliveryState(delivery.state) if delivery else None,
            delivery.id if delivery else None,
            list(delivery.message_ids) if delivery else [],
        )

    async def briefing_on(self, owner_id: int, day: date) -> StoredBriefing | None:
        return await self._load(
            (BriefingRow.owner_id == owner_id) & (BriefingRow.briefing_date == day)
        )

    async def latest_briefing(
        self, owner_id: int, before: date | None = None
    ) -> StoredBriefing | None:
        condition = BriefingRow.owner_id == owner_id
        if before is not None:
            condition = condition & (BriefingRow.briefing_date < before)
        return await self._load(condition)

    async def briefing_by_id(self, briefing_id: int) -> StoredBriefing | None:
        return await self._load(BriefingRow.id == briefing_id)

    async def briefing_for_delivery(self, delivery_id: int) -> StoredBriefing | None:
        return await self._load(DeliveryRow.id == delivery_id)

    async def recent_briefings(
        self, owner_id: int, limit: int = 7
    ) -> list[tuple[date, str, str | None]]:
        rows = await self.s.execute(
            select(BriefingRow.briefing_date, BriefingRow.mode, DeliveryRow.state)
            .outerjoin(DeliveryRow, DeliveryRow.briefing_id == BriefingRow.id)
            .where(BriefingRow.owner_id == owner_id)
            .order_by(BriefingRow.briefing_date.desc())
            .limit(limit)
        )
        return [(d, m, s) for d, m, s in rows.all()]

    # ----------------------------------------------------------------- delivery transitions

    async def claim_delivery(
        self, delivery_id: int, *, allowed: frozenset[DeliveryState], now: datetime
    ) -> uuid.UUID | None:
        token = uuid.uuid4()
        claimed = await self.s.scalar(
            update(DeliveryRow)
            .where(DeliveryRow.id == delivery_id, DeliveryRow.state.in_([s.value for s in allowed]))
            .values(
                state=DeliveryState.SENDING.value,
                claim_token=token,
                attempts=DeliveryRow.attempts + 1,
                updated_at=now,
            )
            .returning(DeliveryRow.id)
        )
        return token if claimed is not None else None

    async def delivery_message_ids(self, delivery_id: int) -> list[int | None]:
        ids = await self.s.scalar(
            select(DeliveryRow.message_ids).where(DeliveryRow.id == delivery_id)
        )
        return list(ids or [])

    async def record_chunk(
        self, delivery_id: int, token: uuid.UUID, index: int, message_id: int
    ) -> None:
        row = await self.s.scalar(
            select(DeliveryRow)
            .where(DeliveryRow.id == delivery_id, DeliveryRow.claim_token == token)
            .with_for_update()
        )
        if row is None:
            raise RuntimeError("delivery claim lost")
        ids = list(row.message_ids)
        ids[index] = message_id
        row.message_ids = ids

    async def finish_delivery(
        self,
        delivery_id: int,
        token: uuid.UUID,
        state: DeliveryState,
        now: datetime,
        error_class: str | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "state": state.value,
            "updated_at": now,
            "error_class": error_class,
        }
        if state in (DeliveryState.SENT, DeliveryState.RESENT):
            values["sent_at"] = now
        if state is DeliveryState.HELD:
            values["held_at"] = now
        await self.s.execute(
            update(DeliveryRow)
            .where(DeliveryRow.id == delivery_id, DeliveryRow.claim_token == token)
            .values(**values)
        )

    async def hold_stale_sending(
        self, now: datetime, *, owner_id: int | None = None, delivery_id: int | None = None
    ) -> int:
        """Hold deliveries whose sender died mid-send. Their unsent chunks wait for the owner.

        Clearing the claim token means a sender that is somehow still alive can record nothing.
        """
        condition = (DeliveryRow.state == DeliveryState.SENDING.value) & (
            DeliveryRow.updated_at < now - STALE_SENDING
        )
        if owner_id is not None:
            condition = condition & (DeliveryRow.owner_id == owner_id)
        if delivery_id is not None:
            condition = condition & (DeliveryRow.id == delivery_id)
        result = await self.s.execute(
            update(DeliveryRow)
            .where(condition)
            .values(
                state=DeliveryState.HELD.value,
                claim_token=None,
                error_class="stale_sending",
                held_at=now,
                updated_at=now,
            )
        )
        return int(result.rowcount)  # type: ignore[attr-defined]

    async def held_deliveries(self, owner_id: int) -> list[StoredBriefing]:
        ids = await self.s.scalars(
            select(DeliveryRow.briefing_id)
            .where(DeliveryRow.owner_id == owner_id, DeliveryRow.state == DeliveryState.HELD.value)
            .order_by(DeliveryRow.briefing_date.desc())
        )
        loaded = [await self.briefing_by_id(i) for i in ids]
        return [b for b in loaded if b is not None]

    async def dismiss_held(self, delivery_id: int, now: datetime) -> bool:
        result = await self.s.scalar(
            update(DeliveryRow)
            .where(DeliveryRow.id == delivery_id, DeliveryRow.state == DeliveryState.HELD.value)
            .values(
                state=DeliveryState.DISMISSED.value,
                resolution="dismissed",
                resolved_at=now,
                updated_at=now,
            )
            .returning(DeliveryRow.id)
        )
        return result is not None

    async def on_time_rate(
        self, owner_id: int, since: date, deadline_hour_utc: int
    ) -> tuple[int, int]:
        """(delivered by deadline, days with a briefing) since `since`."""
        rows = (
            await self.s.execute(
                select(DeliveryRow.briefing_date, DeliveryRow.sent_at).where(
                    DeliveryRow.owner_id == owner_id, DeliveryRow.briefing_date >= since
                )
            )
        ).all()
        on_time = sum(
            1
            for day, sent in rows
            if sent is not None
            and sent
            <= datetime.combine(day, datetime.min.time(), sent.tzinfo).replace(
                hour=deadline_hour_utc
            )
        )
        return on_time, len(rows)
