"""Instruments, watchlists, bars, FX, fundamentals and corporate actions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lens.domain.bars import Bar, BarQuality
from lens.domain.instruments import AssetClass, Instrument, Market
from lens.domain.portfolio import FxRate
from lens.domain.reasons import ReasonCode
from lens.domain.strategy.base import Fundamentals
from lens.storage.models import (
    BarRevision,
    BarRow,
    CorporateAction,
    FundamentalsRow,
    FxRateRow,
    InstrumentRow,
    Owner,
    WatchlistRow,
)

REVISION_TOLERANCE = Decimal("0.0001")


def _instrument(row: InstrumentRow) -> Instrument:
    return Instrument(
        row.symbol, row.name, AssetClass(row.asset_class), Market(row.market), row.currency
    )


class MarketRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def ensure_owner(self, owner_id: int, base_currency: str, timezone: str) -> None:
        await self.s.execute(
            insert(Owner)
            .values(id=owner_id, base_currency=base_currency, timezone=timezone)
            .on_conflict_do_nothing(index_elements=[Owner.id])
        )

    async def ensure_instruments(self, instruments: Iterable[Instrument]) -> dict[str, int]:
        items = list(instruments)
        if items:
            await self.s.execute(
                insert(InstrumentRow)
                .values(
                    [
                        {
                            "symbol": i.symbol,
                            "name": i.name,
                            "asset_class": i.asset_class.value,
                            "market": i.market.value,
                            "currency": i.currency,
                        }
                        for i in items
                    ]
                )
                .on_conflict_do_nothing(index_elements=[InstrumentRow.symbol])
            )
        rows = await self.s.execute(
            select(InstrumentRow.symbol, InstrumentRow.id).where(
                InstrumentRow.symbol.in_([i.symbol for i in items])
            )
        )
        return dict(rows.all())

    async def instrument_ids(self, symbols: Iterable[str]) -> dict[str, int]:
        rows = await self.s.execute(
            select(InstrumentRow.symbol, InstrumentRow.id).where(
                InstrumentRow.symbol.in_(list(symbols))
            )
        )
        return dict(rows.all())

    async def instrument(self, symbol: str) -> Instrument | None:
        row = await self.s.scalar(select(InstrumentRow).where(InstrumentRow.symbol == symbol))
        return None if row is None else _instrument(row)

    async def seed_watchlist(self, owner_id: int, instruments: Sequence[Instrument]) -> None:
        """Add the configured watchlist once. Later edits through the bot are kept."""
        existing = await self.s.scalar(
            select(WatchlistRow.owner_id).where(WatchlistRow.owner_id == owner_id).limit(1)
        )
        if existing is not None:
            return
        ids = await self.ensure_instruments(instruments)
        await self.s.execute(
            insert(WatchlistRow)
            .values([{"owner_id": owner_id, "instrument_id": ids[i.symbol]} for i in instruments])
            .on_conflict_do_nothing()
        )

    async def watchlist(self, owner_id: int) -> list[Instrument]:
        rows = await self.s.scalars(
            select(InstrumentRow)
            .join(WatchlistRow, WatchlistRow.instrument_id == InstrumentRow.id)
            .where(WatchlistRow.owner_id == owner_id, WatchlistRow.active.is_(True))
            .order_by(InstrumentRow.id)
        )
        return [_instrument(row) for row in rows]

    async def set_watched(self, owner_id: int, instrument: Instrument, active: bool) -> None:
        ids = await self.ensure_instruments([instrument])
        statement = insert(WatchlistRow).values(
            owner_id=owner_id, instrument_id=ids[instrument.symbol], active=active
        )
        await self.s.execute(
            statement.on_conflict_do_update(
                index_elements=[WatchlistRow.owner_id, WatchlistRow.instrument_id],
                set_={"active": active},
            )
        )

    async def instruments_by_symbol(self, symbols: Iterable[str]) -> dict[str, Instrument]:
        rows = await self.s.scalars(
            select(InstrumentRow).where(InstrumentRow.symbol.in_(list(symbols)))
        )
        return {row.symbol: _instrument(row) for row in rows}

    async def load_bars(
        self, symbols: Iterable[str], since: date | None = None
    ) -> dict[str, list[Bar]]:
        query = (
            select(InstrumentRow.symbol, BarRow)
            .join(BarRow, BarRow.instrument_id == InstrumentRow.id)
            .where(InstrumentRow.symbol.in_(list(symbols)))
            .order_by(InstrumentRow.symbol, BarRow.day)
        )
        if since is not None:
            query = query.where(BarRow.day >= since)
        result: dict[str, list[Bar]] = {}
        for symbol, row in (await self.s.execute(query)).all():
            result.setdefault(symbol, []).append(
                Bar(
                    symbol,
                    row.day,
                    row.open,
                    row.high,
                    row.low,
                    row.close,
                    row.volume,
                    row.provider,
                    BarQuality(row.quality),
                    tuple(ReasonCode(r) for r in row.reasons),
                )
            )
        return result

    async def upsert_bars(self, instrument_id: int, bars: Sequence[Bar]) -> int:
        """Store bars; record a revision when a stored close changes. Returns revisions found."""
        if not bars:
            return 0
        existing = dict(
            (
                await self.s.execute(
                    select(BarRow.day, BarRow.close).where(
                        BarRow.instrument_id == instrument_id, BarRow.day.in_([b.day for b in bars])
                    )
                )
            ).all()
        )
        revisions = [
            {
                "instrument_id": instrument_id,
                "day": b.day,
                "old_close": existing[b.day],
                "new_close": b.close,
                "provider": b.provider,
            }
            for b in bars
            if b.day in existing
            and existing[b.day] > 0
            and abs(b.close / existing[b.day] - 1) > REVISION_TOLERANCE
        ]
        statement = insert(BarRow).values(
            [
                {
                    "instrument_id": instrument_id,
                    "day": b.day,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                    "provider": b.provider,
                    "quality": b.quality.value,
                    "reasons": [r.value for r in b.reasons],
                }
                for b in bars
            ]
        )
        await self.s.execute(
            statement.on_conflict_do_update(
                index_elements=[BarRow.instrument_id, BarRow.day],
                set_={
                    name: statement.excluded[name]
                    for name in (
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "provider",
                        "quality",
                        "reasons",
                        "fetched_at",
                    )
                },
            )
        )
        if revisions:
            await self.s.execute(insert(BarRevision).values(revisions))
        return len(revisions)

    async def record_splits(
        self, instrument_id: int, splits: Mapping[date, Decimal], source: str
    ) -> None:
        if not splits:
            return
        await self.s.execute(
            insert(CorporateAction)
            .values(
                [
                    {
                        "instrument_id": instrument_id,
                        "day": d,
                        "kind": "split",
                        "ratio": r,
                        "source": source,
                    }
                    for d, r in splits.items()
                ]
            )
            .on_conflict_do_nothing()
        )

    async def save_fx(self, rate: FxRate) -> None:
        statement = insert(FxRateRow).values(
            currency=rate.quote, quote=rate.base, day=rate.day, rate=rate.rate, source=rate.source
        )
        await self.s.execute(
            statement.on_conflict_do_update(
                index_elements=[FxRateRow.currency, FxRateRow.quote, FxRateRow.day],
                set_={"rate": statement.excluded.rate, "source": statement.excluded.source},
            )
        )

    async def latest_fx(self, currency: str, quote: str, on_or_before: date) -> FxRate | None:
        row = await self.s.scalar(
            select(FxRateRow)
            .where(
                FxRateRow.currency == currency,
                FxRateRow.quote == quote,
                FxRateRow.day <= on_or_before,
            )
            .order_by(FxRateRow.day.desc())
            .limit(1)
        )
        return (
            None if row is None else FxRate(row.currency, row.quote, row.rate, row.day, row.source)
        )

    async def fundamentals(self, symbols: Iterable[str]) -> dict[str, Fundamentals]:
        rows = await self.s.execute(
            select(InstrumentRow.symbol, FundamentalsRow)
            .join(FundamentalsRow, FundamentalsRow.instrument_id == InstrumentRow.id)
            .where(InstrumentRow.symbol.in_(list(symbols)))
        )
        return {
            symbol: Fundamentals(row.pe_ratio, row.revenue_growth_pct, row.as_of)
            for symbol, row in rows.all()
        }

    async def save_fundamentals(self, instrument_id: int, data: Fundamentals) -> None:
        statement = insert(FundamentalsRow).values(
            instrument_id=instrument_id,
            pe_ratio=data.pe_ratio,
            revenue_growth_pct=data.revenue_growth_pct,
            as_of=data.as_of,
        )
        await self.s.execute(
            statement.on_conflict_do_update(
                index_elements=[FundamentalsRow.instrument_id],
                set_={
                    "pe_ratio": statement.excluded.pe_ratio,
                    "revenue_growth_pct": statement.excluded.revenue_growth_pct,
                    "as_of": statement.excluded.as_of,
                },
            )
        )
