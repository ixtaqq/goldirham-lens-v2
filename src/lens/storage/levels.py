"""Price-level alerts the owner set. Active means neither triggered nor cancelled."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lens.domain.alerts import Direction
from lens.storage.models import InstrumentRow, LevelAlertRow


@dataclass(frozen=True, slots=True)
class StoredLevelAlert:
    id: int
    symbol: str
    direction: Direction
    level: Decimal
    created_on: date
    triggered_on: date | None
    triggered_close: Decimal | None


_ACTIVE = LevelAlertRow.triggered_on.is_(None) & LevelAlertRow.cancelled_at.is_(None)


class LevelAlertRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def add(
        self,
        owner_id: int,
        instrument_id: int,
        direction: Direction,
        level: Decimal,
        created_on: date,
    ) -> int:
        row = LevelAlertRow(
            owner_id=owner_id,
            instrument_id=instrument_id,
            direction=direction.value,
            level=level,
            created_on=created_on,
        )
        self.s.add(row)
        await self.s.flush()
        return row.id

    async def _list(self, condition: Any, order: Any, limit: int | None) -> list[StoredLevelAlert]:
        rows = await self.s.execute(
            select(LevelAlertRow, InstrumentRow.symbol)
            .join(InstrumentRow, InstrumentRow.id == LevelAlertRow.instrument_id)
            .where(condition)
            .order_by(*order)
            .limit(limit)
        )
        return [
            StoredLevelAlert(
                row.id,
                symbol,
                Direction(row.direction),
                row.level,
                row.created_on,
                row.triggered_on,
                row.triggered_close,
            )
            for row, symbol in rows.all()
        ]

    async def active(self, owner_id: int) -> list[StoredLevelAlert]:
        return await self._list(
            (LevelAlertRow.owner_id == owner_id) & _ACTIVE, (LevelAlertRow.id,), None
        )

    async def recent(self, owner_id: int, limit: int = 5) -> list[StoredLevelAlert]:
        """Triggered alerts, newest first."""
        return await self._list(
            (LevelAlertRow.owner_id == owner_id) & LevelAlertRow.triggered_on.is_not(None),
            (LevelAlertRow.triggered_on.desc(), LevelAlertRow.id.desc()),
            limit,
        )

    async def cancel(self, owner_id: int, alert_id: int, now: datetime) -> bool:
        result = await self.s.scalar(
            update(LevelAlertRow)
            .where(LevelAlertRow.id == alert_id, LevelAlertRow.owner_id == owner_id, _ACTIVE)
            .values(cancelled_at=now)
            .returning(LevelAlertRow.id)
        )
        return result is not None

    async def mark_triggered(self, alert_id: int, day: date, close: Decimal) -> bool:
        """Record the crossing once. A second call, or a call after cancelling, changes nothing."""
        result = await self.s.scalar(
            update(LevelAlertRow)
            .where(LevelAlertRow.id == alert_id, _ACTIVE)
            .values(triggered_on=day, triggered_close=close)
            .returning(LevelAlertRow.id)
        )
        return result is not None
