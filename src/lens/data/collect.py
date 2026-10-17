"""Collect completed daily bars per asset, cross-check recent closes, and assess quality."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from lens.data.calendars import calendar_for
from lens.data.providers.alphavantage import AlphaVantageProvider
from lens.data.providers.base import BarProvider, CallLog, ProviderBars, ProviderError
from lens.data.providers.exchanges import BinanceProvider, CoinbaseProvider
from lens.data.providers.yahoo import YahooProvider
from lens.domain.bars import Bar
from lens.domain.instruments import AssetClass, Instrument, Market
from lens.domain.readiness import Readiness, assess_readiness
from lens.domain.reasons import ReasonCode
from lens.domain.validation import QualityInputs, assess
from lens.settings import Settings

ProviderFactory = Callable[[CallLog], BarProvider]


def provider_factories(alpha_vantage_key: str | None = None) -> dict[str, ProviderFactory]:
    return {
        "yahoo": lambda log: YahooProvider(log),
        "coinbase": lambda log: CoinbaseProvider(log=log),
        "binance": lambda log: BinanceProvider(log=log),
        "alphavantage": lambda log: AlphaVantageProvider(alpha_vantage_key, log=log),
    }


CONCURRENCY = {"yahoo": 3, "coinbase": 2, "binance": 2, "alphavantage": 1}


@dataclass(frozen=True, slots=True)
class AssetData:
    instrument: Instrument
    bars: tuple[Bar, ...]
    closed_sessions: tuple[date, ...]
    readiness: Readiness
    primary: str
    cross_check: str | None
    errors: tuple[str, ...] = ()
    splits: Mapping[date, Decimal] = field(default_factory=dict)

    @property
    def latest(self) -> Bar | None:
        return self.bars[-1] if self.bars else None


@dataclass(slots=True)
class Collector:
    settings: Settings
    now: datetime
    log: CallLog = field(default_factory=CallLog)
    factories: Mapping[str, ProviderFactory] = field(default_factory=provider_factories)
    _providers: dict[str, BarProvider] = field(default_factory=dict)
    _limits: dict[str, asyncio.Semaphore] = field(default_factory=dict)

    def provider(self, name: str) -> BarProvider:
        if name not in self._providers:
            self._providers[name] = self.factories[name](self.log)
            self._limits[name] = asyncio.Semaphore(CONCURRENCY.get(name, 2))
        return self._providers[name]

    async def _fetch(
        self, name: str, instrument: Instrument, start: date, end: date
    ) -> ProviderBars:
        provider = self.provider(name)
        async with self._limits[name]:
            return await provider.fetch_daily(instrument, start, end)

    async def collect(self, instrument: Instrument, stored: Sequence[Bar] = ()) -> AssetData:
        data = self.settings.data
        choice = self.settings.providers.for_instrument(instrument)
        calendar = calendar_for(
            instrument.market, frozenset(self.settings.calendar_holidays.get(instrument.market, ()))
        )
        closed = [s.day for s in calendar.closed_sessions(self.now, data.history_sessions)]
        if not closed:
            raise ValueError(f"no closed sessions for {instrument.market}")
        closed_set = set(closed)
        errors: list[str] = []
        splits: Mapping[date, Decimal] = {}
        primary_failed = False
        try:
            primary = await self._fetch(choice.primary, instrument, closed[0], closed[-1])
            bars = [b for b in primary.bars if b.day in closed_set]
            splits = primary.splits
        except ProviderError as error:
            errors.append(str(error))
            primary_failed = True
            bars = [b for b in stored if b.day in closed_set]

        recent = closed[-data.cross_check_sessions :]
        cross_closes: dict[date, Decimal] = {}
        cross_ok = False
        if choice.cross_check:
            try:
                secondary = await self._fetch(choice.cross_check, instrument, recent[0], recent[-1])
                cross_closes = {b.day: b.close for b in secondary.bars if b.day in closed_set}
                cross_ok = True
            except ProviderError as error:
                errors.append(str(error))

        assessed = assess(
            bars,
            QualityInputs(
                jump_threshold_pct=data.suspect_jump_pct.get(instrument.asset_class, Decimal(20)),
                cross_check_tolerance_pct=data.cross_check_tolerance_pct,
                cross_check_days=frozenset(recent),
                cross_check_closes=cross_closes,
                cross_check_available=cross_ok,
                confirmed_splits=splits,
                splits_possible=instrument.asset_class is not AssetClass.CRYPTO,
            ),
        )
        readiness = assess_readiness(
            assessed,
            closed[-data.min_sessions :],
            single_source_allowed=instrument.market in data.single_source_allowed_markets,
            recent_sessions=data.cross_check_sessions,
        )
        if primary_failed:
            readiness = Readiness(
                (ReasonCode.PROVIDER_UNAVAILABLE, *readiness.reasons),
                readiness.latest_session,
                readiness.verified_sessions,
                readiness.required_sessions,
            )
        return AssetData(
            instrument,
            tuple(assessed),
            tuple(closed),
            readiness,
            choice.primary,
            choice.cross_check,
            tuple(errors),
            splits,
        )

    async def collect_all(
        self, instruments: Sequence[Instrument], stored: Mapping[str, Sequence[Bar]] | None = None
    ) -> dict[str, AssetData]:
        stored = stored or {}
        results = await asyncio.gather(
            *(self.collect(i, stored.get(i.symbol, ())) for i in instruments)
        )
        return {item.instrument.symbol: item for item in results}


def calendar_gaps(data: Mapping[str, AssetData]) -> dict[Market, list[date]]:
    """Sessions the calendar expects that every asset of a market lacks: likely unlisted holidays."""
    by_market: dict[Market, list[AssetData]] = {}
    for item in data.values():
        by_market.setdefault(item.instrument.market, []).append(item)
    gaps: dict[Market, list[date]] = {}
    for market, items in by_market.items():
        if len(items) < 2 or market is Market.CRYPTO_UTC:
            continue
        missing = None
        for item in items:
            days = {b.day for b in item.bars}
            expected = set(item.closed_sessions[-item.readiness.required_sessions :])
            lacking = expected - days
            missing = lacking if missing is None else missing & lacking
        if missing:
            gaps[market] = sorted(missing)
    return gaps
