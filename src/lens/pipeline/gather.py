"""All I/O before analysis: database reads, provider collection, FX, context. Builds CycleInputs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from lens.data.collect import AssetData, Collector
from lens.data.providers.base import CallLog, ProviderError
from lens.data.providers.context import FearGreed, fetch_fear_greed, fetch_headlines
from lens.data.providers.fx import fetch_myr_rate
from lens.data.providers.yahoo import fetch_fundamentals_sync
from lens.domain.briefing import BriefingDocument, Headline
from lens.domain.instruments import AssetClass, Instrument
from lens.domain.money import NonFiniteNumberError, to_decimal
from lens.domain.portfolio import FxRate, build_positions
from lens.domain.strategy.base import Fundamentals
from lens.logs import get_logger
from lens.pipeline.analysis import strategies_from
from lens.pipeline.inputs import (
    AssetIn,
    BarIn,
    ContextIn,
    CycleInputs,
    FundamentalsIn,
    FxIn,
    PreviousIn,
    SignalIn,
    TxIn,
)
from lens.settings import Settings
from lens.storage.cycles import CycleRepo
from lens.storage.db import Database
from lens.storage.ledger import LedgerRepo
from lens.storage.market import MarketRepo
from lens.storage.ops import OpsRepo
from lens.storage.signals import SignalRepo
from lens.storage.strategies import StrategyRepo

log = get_logger("lens.pipeline.gather")
FUNDAMENTALS_MAX_AGE = timedelta(days=7)
STORED_HISTORY = timedelta(days=800)


async def _default_fundamentals(stale: list[Instrument]) -> dict[str, Fundamentals]:
    return await _fundamentals(stale)


@dataclass(frozen=True, slots=True)
class External:
    """Network sources outside the bar providers. Tests replace these."""

    fx: Callable[[str, CallLog], Awaitable[FxRate]] = lambda currency, log: fetch_myr_rate(
        currency, log=log
    )
    fear_greed: Callable[[Settings, CallLog], Awaitable[FearGreed]] = lambda settings, log: (
        fetch_fear_greed(settings.context.fear_greed_url, log=log)
    )
    headlines: Callable[[Settings, CallLog], Awaitable[list[Headline]]] = lambda settings, log: (
        fetch_headlines(settings.context.headline_feeds, settings.context.max_headlines, log=log)
    )
    fundamentals: Callable[[list[Instrument]], Awaitable[dict[str, Fundamentals]]] = (
        _default_fundamentals
    )


@dataclass(frozen=True, slots=True)
class Gathered:
    inputs: CycleInputs
    data: dict[str, AssetData]
    calls: CallLog


def benchmark_instruments(settings: Settings) -> list[Instrument]:
    result = []
    for symbol in settings.benchmarks.values():
        asset_class = AssetClass.CRYPTO if symbol.endswith("-USD") else AssetClass.ETF
        result.append(
            Instrument.create(symbol, asset_class, "FBM KLCI" if symbol == "^KLSE" else None)
        )
    return result


def universe(
    settings: Settings,
    watched: Sequence[Instrument],
    held: set[str],
    known: Mapping[str, Instrument],
) -> list[Instrument]:
    """The watchlist, then benchmarks and held positions not on it, each symbol once."""
    extra = [known.get(b.symbol, b) for b in benchmark_instruments(settings)]
    extra += [known[s] for s in sorted(held) if s in known]
    everything: dict[str, Instrument] = {}
    for instrument in (*watched, *extra):
        everything.setdefault(instrument.symbol, instrument)
    return list(everything.values())


def _asset_in(data: AssetData, watched: bool) -> AssetIn:
    i = data.instrument
    return AssetIn(
        symbol=i.symbol,
        name=i.name,
        asset_class=i.asset_class,
        market=i.market,
        currency=i.currency,
        watched=watched,
        closed_sessions=data.closed_sessions,
        bars=tuple(BarIn.of(b) for b in data.bars),
        readiness=data.readiness.reasons,
        primary=data.primary,
        cross_check=data.cross_check,
        errors=data.errors,
    )


def _failed_sources(data: dict[str, AssetData]) -> list[str]:
    """One line per failing provider, with its first error message."""
    first: dict[str, str] = {}
    for item in data.values():
        for error in item.errors:
            provider, _, message = error.partition(": ")
            first.setdefault(provider, message)
    return [
        f"{provider} ({message})" if message else provider
        for provider, message in sorted(first.items())
    ]


async def _fundamentals(stale: list[Instrument]) -> dict[str, Fundamentals]:
    fresh: dict[str, Fundamentals] = {}
    today = date.today()  # noqa: DTZ011 - as-of label for data fetched now
    for instrument in stale:
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(fetch_fundamentals_sync, instrument.symbol), 30
            )
        except Exception as error:
            log.warning(
                "fundamentals unavailable", symbol=instrument.symbol, error=type(error).__name__
            )
            continue
        try:
            pe = to_decimal(raw["pe_ratio"]) if raw.get("pe_ratio") is not None else None
            growth = (
                to_decimal(raw["revenue_growth"]) * 100
                if raw.get("revenue_growth") is not None
                else None
            )
        except NonFiniteNumberError:
            continue
        fresh[instrument.symbol] = Fundamentals(pe, growth, today)
    return fresh


async def _context(
    settings: Settings, calls: CallLog, unavailable: list[str], external: External
) -> ContextIn:
    fear = None
    try:
        fear = await external.fear_greed(settings, calls)
    except ProviderError:
        unavailable.append("fear & greed index")
    headlines: list[Headline] = []
    if settings.context.headline_feeds and settings.context.max_headlines:
        headlines = await external.headlines(settings, calls)
        if not headlines:
            unavailable.append("headlines")
    return ContextIn(
        fear_greed=fear.value if fear else None,
        fear_greed_label=fear.label if fear else None,
        headlines=tuple(headlines),
    )


async def gather(
    db: Database,
    settings: Settings,
    *,
    now: datetime,
    briefing_date: date,
    owner_id: int,
    cycle_id: str,
    trigger: str,
    late: bool,
    collector: Collector | None = None,
    persist_reference_data: bool = True,
    external: External | None = None,
) -> Gathered:
    external = external or External()
    instruments = settings.instruments()
    async with db.session() as session:
        market = MarketRepo(session)
        await market.ensure_owner(owner_id, settings.owner.base_currency, settings.owner.timezone)
        await market.seed_watchlist(owner_id, instruments)
        watched = await market.watchlist(owner_id)
        transactions = await LedgerRepo(session).transactions(owner_id)
        held = {s for s, p in build_positions(transactions).items() if p.quantity > 0}
        known = await market.instruments_by_symbol(
            held | {b.symbol for b in benchmark_instruments(settings)}
        )
        open_signals = await SignalRepo(session).open_signals(owner_id)
        previous = await CycleRepo(session).latest_briefing(owner_id, before=briefing_date)
        previous_reviews = await SignalRepo(session).previous_reviews(owner_id, briefing_date)
        strategies = StrategyRepo(session)
        for configured in strategies_from(settings):
            await strategies.ensure(configured)
        active = await strategies.active_versions()
        prefs = await OpsRepo(session).preferences(owner_id)
        watched_symbols = {i.symbol for i in watched}
        everything = universe(settings, watched, held, known)
        stored = await market.load_bars(
            [i.symbol for i in everything], since=briefing_date - STORED_HISTORY
        )
        fundamentals = await market.fundamentals([i.symbol for i in everything])

    calls = CallLog()
    collector = collector or Collector(settings, now, calls)
    calls = collector.log
    data = await collector.collect_all(everything, stored)

    stale = [
        i
        for i in watched
        if i.asset_class is AssetClass.STOCK
        and (
            i.symbol not in fundamentals
            or briefing_date - fundamentals[i.symbol].as_of > FUNDAMENTALS_MAX_AGE
        )
    ]
    refreshed = await external.fundamentals(stale) if persist_reference_data and stale else {}
    fundamentals.update(refreshed)

    unavailable = _failed_sources(data)
    currencies = sorted(
        ({i.currency for i in everything} | {t.currency for t in transactions})
        - {settings.owner.base_currency}
    )
    rates: list[FxRate] = []
    async with db.session() as session:
        market = MarketRepo(session)
        for currency in currencies:
            rate: FxRate | None
            try:
                rate = await external.fx(currency, calls)
                if persist_reference_data:
                    await market.save_fx(rate)
            except ProviderError:
                unavailable.append(f"FX {currency}/MYR")
                rate = await market.latest_fx(currency, settings.owner.base_currency, briefing_date)
            if rate is not None:
                rates.append(rate)
        if persist_reference_data and refreshed:
            ids = await market.instrument_ids(refreshed)
            for symbol, item in refreshed.items():
                await market.save_fundamentals(ids[symbol], item)

    context = await _context(settings, calls, unavailable, external)
    previous_in = None
    if previous is not None:
        doc = BriefingDocument.model_validate(previous.document)
        previous_in = PreviousIn(
            briefing_date=previous.briefing_date, setup_symbols=tuple(s.symbol for s in doc.setups)
        )

    inputs = CycleInputs(
        briefing_date=briefing_date,
        generated_at=now,
        cycle_id=cycle_id,
        trigger=trigger,
        mode="deterministic",
        degraded_reason=None,
        late=late,
        owner_id=owner_id,
        base_currency=settings.owner.base_currency,
        detail="detailed"
        if prefs.detail == "detailed"
        else "concise"
        if prefs.detail
        else settings.owner.detail,
        risk_per_trade_pct=prefs.risk_per_trade_pct or settings.risk.risk_per_trade_pct,
        settings=settings.model_dump(mode="json"),
        active_versions=tuple(sorted(active)),
        assets=tuple(
            _asset_in(data[i.symbol], i.symbol in watched_symbols)
            for i in everything
            if i.symbol in data
        ),
        signals=tuple(
            SignalIn(
                id=s.id,
                symbol=s.symbol,
                strategy=s.strategy,
                signal_day=s.signal_day,
                expiry_days=s.expiry_days,
                entry=s.levels.entry,
                stop=s.levels.stop,
                t1=s.levels.t1,
                t2=s.levels.t2,
                status=s.state.status,
                last_evaluated=s.state.last_evaluated,
                t1_touched_on=s.state.t1_touched_on,
                mfe_r=s.state.mfe_r,
                mae_r=s.state.mae_r,
                last_close=s.state.last_close,
            )
            for s in open_signals
        ),
        transactions=tuple(
            TxIn(
                id=t.id,
                symbol=t.symbol,
                kind=t.kind,
                day=t.day,
                currency=t.currency,
                quantity=t.quantity,
                price=t.price,
                fee=t.fee,
                amount=t.amount,
                ratio=t.ratio,
            )
            for t in transactions
        ),
        fx=tuple(
            FxIn(quote=r.quote, base=r.base, rate=r.rate, day=r.day, source=r.source) for r in rates
        ),
        fundamentals=tuple(
            FundamentalsIn(
                symbol=s,
                pe_ratio=f.pe_ratio,
                revenue_growth_pct=f.revenue_growth_pct,
                as_of=f.as_of,
            )
            for s, f in sorted(fundamentals.items())
        ),
        previous=previous_in,
        previous_reviews=previous_reviews,
        context=context,
        sources_unavailable=tuple(dict.fromkeys(unavailable)),
    )
    return Gathered(inputs, data, calls)
