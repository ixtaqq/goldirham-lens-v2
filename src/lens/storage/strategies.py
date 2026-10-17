"""Strategy versions, backtest reports, and the activation gate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lens.domain.strategy.registry import ConfiguredStrategy
from lens.storage.models import BacktestReportRow, StrategyVersionRow


class ActivationRefusedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VersionInfo:
    version: str
    name: str
    params: dict[str, Any]
    activated_at: datetime | None
    report_id: int | None


class StrategyRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def ensure(self, configured: ConfiguredStrategy) -> None:
        await self.s.execute(
            insert(StrategyVersionRow)
            .values(
                version=configured.version,
                name=configured.name,
                params=configured.params.model_dump(mode="json"),
                code_version=configured.strategy.code_version,
            )
            .on_conflict_do_nothing(index_elements=[StrategyVersionRow.version])
        )

    async def active_versions(self) -> set[str]:
        rows = await self.s.scalars(
            select(StrategyVersionRow.version).where(StrategyVersionRow.activated_at.is_not(None))
        )
        return set(rows)

    async def versions(self) -> list[VersionInfo]:
        rows = await self.s.scalars(
            select(StrategyVersionRow).order_by(StrategyVersionRow.created_at)
        )
        return [VersionInfo(r.version, r.name, r.params, r.activated_at, r.report_id) for r in rows]

    async def save_report(
        self,
        *,
        version: str,
        name: str,
        params: dict[str, Any],
        from_day: date,
        to_day: date,
        report: dict[str, Any],
        report_hash: str,
    ) -> int:
        report_id = await self.s.scalar(
            insert(BacktestReportRow)
            .values(
                strategy_version=version,
                name=name,
                params=params,
                from_day=from_day,
                to_day=to_day,
                report=report,
                report_hash=report_hash,
            )
            .returning(BacktestReportRow.id)
        )
        assert report_id is not None
        return int(report_id)

    async def latest_report(self, version: str) -> BacktestReportRow | None:
        row: BacktestReportRow | None = await self.s.scalar(
            select(BacktestReportRow)
            .where(BacktestReportRow.strategy_version == version)
            .order_by(BacktestReportRow.created_at.desc())
            .limit(1)
        )
        return row

    async def activate(self, name: str, version: str, now: datetime) -> int:
        """Activate an exact version. Refused unless a backtest report exists for that version."""
        report = await self.latest_report(version)
        if report is None:
            raise ActivationRefusedError(
                f"{name} {version} has no backtest report; run `lens backtest` first"
            )
        row = await self.s.get(StrategyVersionRow, version)
        if row is None or row.name != name:
            raise ActivationRefusedError(f"unknown version {version} for {name}")
        await self.s.execute(
            update(StrategyVersionRow)
            .where(StrategyVersionRow.name == name, StrategyVersionRow.version != version)
            .values(activated_at=None)
        )
        row.activated_at = now
        row.report_id = report.id
        return report.id

    async def deactivate(self, name: str) -> None:
        await self.s.execute(
            update(StrategyVersionRow)
            .where(StrategyVersionRow.name == name)
            .values(activated_at=None)
        )
