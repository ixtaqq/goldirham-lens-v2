"""Showcase data: the real validation, analysis, compose and render code over a synthetic market.

Nothing here reads the network or the database. The market is generated from a fixed seed with
integer arithmetic, so the export is byte-identical on every machine. Every figure is demo data.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from lens.backtest.engine import AssetHistory
from lens.backtest.report import build_report
from lens.delivery.chunker import chunk
from lens.delivery.format import long_day, price, r_multiple, short_day, signed_pct
from lens.delivery.renderer import TELEGRAM_LIMIT, render_sections
from lens.domain.bars import Bar
from lens.domain.briefing import Headline
from lens.domain.evaluation import SignalStatus
from lens.domain.indicators import sma_series
from lens.domain.instruments import AssetClass, Instrument, Market
from lens.domain.portfolio import TxKind
from lens.domain.readiness import assess_readiness
from lens.domain.reasons import LABELS, PASS_CODES, ReasonCode
from lens.domain.strategy.base import Decision, RiskInputs
from lens.domain.validation import QualityInputs, assess
from lens.pipeline.analysis import Analysis, analyze, strategies_from
from lens.pipeline.compose import compose
from lens.pipeline.inputs import (
    AssetIn,
    BarIn,
    ContextIn,
    CycleInputs,
    FxIn,
    PreviousIn,
    SignalIn,
    TxIn,
)
from lens.settings import Settings, WatchlistItem

SEED = 20261016
LABEL = "DEMO DATA"
NOTICE = (
    "Generated from a fixed seed by the real pipeline. The market, prices and holdings are "
    "synthetic. Nothing here is a real price, a real portfolio or advice."
)
HISTORY_SESSIONS = 900
WINDOW_SESSIONS = 260
TRACE_POINTS = 160
STORY_POINTS = 120
PRIMARY = "demo feed"
CROSS_CHECK = "demo check"
BRIEFING_DAYS = (date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16))
STRATEGY = "pullback_in_uptrend"
SETUP_SYMBOL = "KSTL"
DISPUTED = {("FERN-USD", date(2026, 10, 13)): 260, ("KSTL", date(2026, 10, 15)): 310}
BP = Decimal(10_000)
MYT = timezone(timedelta(hours=8))


@dataclass(frozen=True, slots=True)
class Spec:
    symbol: str
    name: str
    asset_class: AssetClass
    start: str
    drift_bp: int
    noise_bp: int


SPECS = (
    Spec("NRTH", "Northwind 500 ETF", AssetClass.ETF, "290.00", 3, 85),
    Spec("KSTL", "Kestrel Systems", AssetClass.STOCK, "41.00", 11, 150),
    Spec("ORBT", "Orbit Foods", AssetClass.STOCK, "64.00", 0, 140),
    Spec("9000.KL", "Merbok Composite Tracker", AssetClass.ETF, "1.48", 5, 70),
    Spec("9001.KL", "Selat Holdings", AssetClass.STOCK, "6.10", 2, 120),
    Spec("9002.KL", "Teratai Bank", AssetClass.STOCK, "7.20", 5, 95),
    Spec("BLOK-USD", "Blockmark", AssetClass.CRYPTO, "21000", 9, 330),
    Spec("FERN-USD", "Fern", AssetClass.CRYPTO, "1.90", 4, 460),
)
BENCHMARKS = {Market.XNYS: "NRTH", Market.XKLS: "9000.KL", Market.CRYPTO_UTC: "BLOK-USD"}
# The setup asset's last sessions, in basis points: a pullback that ends in an oversold close.
PULLBACK_BP = (-90, -160, -70, -210, -150, -260, 60)

DAY_COPY = {
    BRIEFING_DAYS[0]: (
        "quiet",
        "Quiet day",
        "Every source verified and no rule fired. The briefing says so once and stops.",
    ),
    BRIEFING_DAYS[1]: (
        "setup",
        "Setup day",
        "Kestrel Systems passes every rule. Fern's latest close disagrees with its cross-check, "
        "so Fern is withheld with its reason code.",
    ),
    BRIEFING_DAYS[2]: (
        "degraded",
        "Degraded data",
        "Kestrel's newest close is disputed, so the setup is withdrawn and the open signal "
        "pauses. The sentiment source did not answer and is listed as unavailable.",
    ),
}
TRANSACTIONS = (
    ("NRTH", "2026-10-05", "USD", "14", "452.10", "1.00"),
    ("ORBT", "2026-08-03", "USD", "70", "88.40", "1.00"),
    ("9000.KL", "2026-05-11", "MYR", "15500", "1.84", "12.00"),
    ("9001.KL", "2026-06-15", "MYR", "3400", "8.20", "12.00"),
    ("9002.KL", "2026-07-20", "MYR", "2700", "10.60", "12.00"),
    ("BLOK-USD", "2026-08-24", "USD", "0.22", "28900", "4.00"),
)
FX_RATES = {
    BRIEFING_DAYS[0]: Decimal("4.4185"),
    BRIEFING_DAYS[1]: Decimal("4.4210"),
    BRIEFING_DAYS[2]: Decimal("4.4167"),
}


def last_session(market: Market, briefing_date: date) -> date:
    """The latest session closed by 07:00 MYT on the briefing date (ADR 0003 for crypto)."""
    if market is Market.CRYPTO_UTC:
        return briefing_date - timedelta(days=2)
    day = briefing_date - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def sessions(market: Market, end: date, count: int) -> list[date]:
    days: list[date] = []
    current = end
    while len(days) < count:
        if market is Market.CRYPTO_UTC or current.weekday() < 5:
            days.append(current)
        current -= timedelta(days=1)
    return days[::-1]


def _step(price_: Decimal, bp: int) -> Decimal:
    return price_ * (BP + bp) / BP


def generate_bars(spec: Spec, settings: Settings, rng: random.Random) -> list[Bar]:
    instrument = Instrument.create(spec.symbol, spec.asset_class, spec.name)
    ticks = settings.tick_rule(instrument.market)
    end = last_session(instrument.market, BRIEFING_DAYS[-1])
    days = sessions(instrument.market, end, HISTORY_SESSIONS)
    steps = [spec.drift_bp + rng.randint(-spec.noise_bp, spec.noise_bp) for _ in days]
    if spec.symbol == SETUP_SYMBOL:
        steps[-len(PULLBACK_BP) :] = PULLBACK_BP
    bars: list[Bar] = []
    close = Decimal(spec.start)
    for day, step in zip(days, steps, strict=True):
        open_ = ticks.nearest(_step(close, rng.randint(-15, 15)))
        close = _step(close, step)
        shown = ticks.nearest(close)
        high = ticks.ceil(_step(max(open_, shown), rng.randint(5, 60)))
        low = ticks.floor(_step(min(open_, shown), -rng.randint(5, 60)))
        volume = Decimal(1_000_000 + rng.randint(-250_000, 250_000))
        bars.append(Bar(instrument.symbol, day, open_, high, low, shown, volume, PRIMARY))
    return bars


def cross_check_closes(
    spec: Spec, bars: list[Bar], rng: random.Random
) -> dict[date, Decimal] | None:
    if Instrument.create(spec.symbol, spec.asset_class).market is Market.XKLS:
        return None
    closes = {}
    for bar in bars:
        offset = DISPUTED.get((spec.symbol, bar.day), rng.randint(-12, 12))
        closes[bar.day] = _step(bar.close, offset).quantize(bar.close)
    return closes


@dataclass(frozen=True, slots=True)
class SyntheticAsset:
    spec: Spec
    instrument: Instrument
    bars: tuple[Bar, ...]
    cross: dict[date, Decimal] | None


def generate_market(settings: Settings) -> tuple[SyntheticAsset, ...]:
    rng = random.Random(SEED)  # noqa: S311 - reproducible synthetic data, not security
    result = []
    for spec in SPECS:
        bars = generate_bars(spec, settings, rng)
        result.append(
            SyntheticAsset(
                spec,
                Instrument.create(spec.symbol, spec.asset_class, spec.name),
                tuple(bars),
                cross_check_closes(spec, bars, rng),
            )
        )
    return tuple(result)


def demo_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "watchlist": tuple(
                WatchlistItem(symbol=s.symbol, asset_class=s.asset_class, name=s.name)
                for s in SPECS
            ),
            "benchmarks": dict(BENCHMARKS),
            "calendar_holidays": {},
        }
    )


def asset_for_day(item: SyntheticAsset, settings: Settings, briefing_date: date) -> AssetIn:
    data = settings.data
    end = last_session(item.instrument.market, briefing_date)
    window = [b for b in item.bars if b.day <= end][-WINDOW_SESSIONS:]
    closed = [b.day for b in window]
    recent = closed[-data.cross_check_sessions :]
    cross = item.cross or {}
    assessed = assess(
        window,
        QualityInputs(
            jump_threshold_pct=data.suspect_jump_pct.get(item.instrument.asset_class, Decimal(20)),
            cross_check_tolerance_pct=data.cross_check_tolerance_pct,
            cross_check_days=frozenset(recent),
            cross_check_closes={d: cross[d] for d in recent if d in cross},
            cross_check_available=item.cross is not None,
            confirmed_splits={},
            splits_possible=item.instrument.asset_class is not AssetClass.CRYPTO,
        ),
    )
    readiness = assess_readiness(
        assessed,
        closed[-data.min_sessions :],
        single_source_allowed=item.instrument.market in data.single_source_allowed_markets,
        recent_sessions=data.cross_check_sessions,
    )
    return AssetIn(
        symbol=item.instrument.symbol,
        name=item.instrument.name,
        asset_class=item.instrument.asset_class,
        market=item.instrument.market,
        currency=item.instrument.currency,
        watched=True,
        closed_sessions=tuple(closed),
        bars=tuple(BarIn.of(b) for b in assessed),
        readiness=readiness.reasons,
        primary=PRIMARY,
        cross_check=CROSS_CHECK if item.cross is not None else None,
    )


def _transactions() -> tuple[TxIn, ...]:
    return tuple(
        TxIn(
            id=index,
            symbol=symbol,
            kind=TxKind.BUY,
            day=date.fromisoformat(day),
            currency=currency,
            quantity=Decimal(quantity),
            price=Decimal(cost),
            fee=Decimal(fee),
            amount=Decimal(0),
            ratio=Decimal(0),
        )
        for index, (symbol, day, currency, quantity, cost, fee) in enumerate(TRANSACTIONS, 1)
    )


def _signal_from(decision: Decision, expiry_days: int) -> SignalIn:
    setup = decision.setup
    assert setup is not None
    return SignalIn(
        id=1,
        symbol=decision.symbol,
        strategy=decision.strategy,
        signal_day=decision.session,
        expiry_days=expiry_days,
        entry=setup.entry,
        stop=setup.stop,
        t1=setup.t1,
        t2=setup.t2,
        status=SignalStatus.OPEN,
        last_evaluated=None,
        t1_touched_on=None,
        mfe_r=Decimal(0),
        mae_r=Decimal(0),
        last_close=None,
    )


@dataclass(frozen=True, slots=True)
class DemoDay:
    inputs: CycleInputs
    analysis: Analysis


def build_days(settings: Settings, market: tuple[SyntheticAsset, ...]) -> list[DemoDay]:
    configured = next(s for s in strategies_from(settings) if s.name == STRATEGY)
    version, expiry = configured.version, configured.params.expiry_days
    days: list[DemoDay] = []
    previous: DemoDay | None = None
    signals: tuple[SignalIn, ...] = ()
    for index, briefing_date in enumerate(BRIEFING_DAYS):
        context_down = index == len(BRIEFING_DAYS) - 1
        inputs = CycleInputs(
            briefing_date=briefing_date,
            generated_at=datetime.combine(
                briefing_date - timedelta(days=1), datetime.min.time()
            ).replace(hour=23, minute=1, tzinfo=UTC),
            cycle_id=f"demo{briefing_date:%m%d}-0000-4000-8000-000000000000",
            trigger="schedule_1",
            mode="deterministic",
            degraded_reason=None,
            late=False,
            owner_id=1,
            base_currency="MYR",
            detail="concise",
            risk_per_trade_pct=settings.risk.risk_per_trade_pct,
            settings=settings.model_dump(mode="json"),
            active_versions=(version,),
            assets=tuple(asset_for_day(item, settings, briefing_date) for item in market),
            signals=signals,
            transactions=_transactions(),
            fx=(
                FxIn(
                    quote="USD",
                    base="MYR",
                    rate=FX_RATES[briefing_date],
                    day=briefing_date - timedelta(days=1),
                    source=PRIMARY,
                ),
            ),
            fundamentals=(),
            previous=(
                PreviousIn(
                    briefing_date=previous.inputs.briefing_date,
                    setup_symbols=tuple(d.symbol for d in previous.analysis.setups),
                )
                if previous
                else None
            ),
            previous_reviews=(
                {s: r.action for s, r in previous.analysis.reviews.items()} if previous else {}
            ),
            context=(
                ContextIn(
                    headlines=(Headline(title="Central bank holds rates", source="Demo Wire"),)
                )
                if context_down
                else ContextIn(
                    fear_greed=58 - 6 * index,
                    fear_greed_label="Greed" if index == 0 else "Neutral",
                    headlines=(Headline(title="Central bank holds rates", source="Demo Wire"),),
                )
            ),
            sources_unavailable=("fear & greed index",) if context_down else (),
        )
        day = DemoDay(inputs, analyze(inputs))
        days.append(day)
        signals = tuple(_signal_from(d, expiry) for d in day.analysis.setups) or signals
        previous = day
    return days


def _rule_trail(decision: Decision) -> list[dict[str, Any]]:
    return [
        {"code": code.value, "label": LABELS[code], "passed": code in PASS_CODES}
        for code in decision.reasons
    ]


def _decision(analysis: Analysis, symbol: str) -> Decision:
    return next(d for d in analysis.assets[symbol].decisions if d.strategy == STRATEGY)


def _indicator_series(day: DemoDay, symbol: str) -> dict[str, list[float | None]]:
    """Close and moving averages for the last sessions, on one shared 0..1 scale."""
    usable = [b for b in day.analysis.assets[symbol].bars if b.usable]
    closes = [float(b.close) for b in usable]
    lines = {
        "close": list[float | None](closes),
        "sma50": sma_series(closes, 50),
        "sma200": sma_series(closes, 200),
    }
    tail = {name: values[-STORY_POINTS:] for name, values in lines.items()}
    present = [v for values in tail.values() for v in values if v is not None]
    low, high = min(present), max(present)
    span = (high - low) or 1.0
    return {
        name: [None if v is None else round((v - low) / span, 3) for v in values]
        for name, values in tail.items()
    }


def pipeline_story(day: DemoDay) -> dict[str, Any]:
    """The setup day, step by step, for the "how a briefing is made" section."""
    arrivals = []
    for asset in day.inputs.assets:
        latest = asset.bars[-1]
        arrivals.append(
            {
                "symbol": asset.symbol,
                "name": asset.name,
                "session": short_day(latest.day),
                "close": price(latest.c, asset.currency),
                "quality": latest.quality.value,
                "reasons": [{"code": r.value, "label": LABELS[r]} for r in latest.reasons],
                "ready": not asset.readiness,
            }
        )
    decision = _decision(day.analysis, SETUP_SYMBOL)
    indicators = decision.indicators
    shown = ("close", "sma50", "sma200", "rsi14", "atr14")
    setup = decision.setup
    assert setup is not None
    currency = day.inputs.asset(SETUP_SYMBOL).currency  # type: ignore[union-attr]
    failing = _decision(day.analysis, "ORBT")
    return {
        "series": _indicator_series(day, SETUP_SYMBOL),
        "briefing_date": day.inputs.briefing_date.isoformat(),
        "arrivals": arrivals,
        "indicators": {
            "symbol": SETUP_SYMBOL,
            "values": [
                {"name": name, "value": f"{Decimal(str(indicators[name])):,.2f}"}
                for name in shown
                if indicators.get(name) is not None
            ],
        },
        "rules": [
            {"symbol": SETUP_SYMBOL, "trail": _rule_trail(decision)},
            {"symbol": "ORBT", "trail": _rule_trail(failing)},
        ],
        "setup": {
            "symbol": SETUP_SYMBOL,
            "entry": price(setup.entry, currency),
            "stop": price(setup.stop, currency),
            "t1": price(setup.t1, currency),
            "t2": price(setup.t2, currency),
            "reward_risk": f"{setup.reward_risk:.2f}",
            "size_pct": f"{setup.size_pct:.2f}%",
        },
    }


def traces(market: tuple[SyntheticAsset, ...]) -> list[list[float]]:
    """Each asset's recent closes scaled to 0..1, for the background field and its poster."""
    result = []
    for item in market:
        closes = [b.close for b in item.bars[-TRACE_POINTS:]]
        low, high = min(closes), max(closes)
        span = high - low or Decimal(1)
        result.append([float(((c - low) / span).quantize(Decimal("0.001"))) for c in closes])
    return result


def _direction(change: Decimal | None) -> str:
    shown = change.quantize(Decimal("0.1")) if change is not None else Decimal(0)
    return "up" if shown > 0 else "down" if shown < 0 else "flat"


def ticker(day: DemoDay) -> list[dict[str, str]]:
    rows = []
    for symbol, analysed in day.analysis.assets.items():
        if analysed.latest is None:
            continue
        rows.append(
            {
                "symbol": symbol,
                "close": price(analysed.latest.close, analysed.asset.currency),
                "change": signed_pct(analysed.change_pct)
                if analysed.change_pct is not None
                else "n/a",
                "direction": _direction(analysed.change_pct),
            }
        )
    return rows


def backtest(settings: Settings, market: tuple[SyntheticAsset, ...]) -> dict[str, Any]:
    configured = next(s for s in strategies_from(settings) if s.name == STRATEGY)
    histories = [
        AssetHistory(item.instrument, item.bars, settings.tick_rule(item.instrument.market))
        for item in market
    ]
    start = min(h.bars[0].day for h in histories)
    end = max(h.bars[-1].day for h in histories)
    report = build_report(
        histories,
        configured,
        RiskInputs(settings.risk.risk_per_trade_pct, settings.risk.max_position_pct),
        start=start,
        end=end,
        min_sessions=settings.data.min_sessions,
        baseline_runs=60,
    )
    body = report.body
    curve = []
    total = Decimal(0)
    resolved = [t for t in body["trades"] if t["outcome_r"] is not None and t["exit_day"]]
    for trade in sorted(resolved, key=lambda t: (t["exit_day"], t["symbol"])):
        total += Decimal(trade["outcome_r"])
        curve.append({"day": trade["exit_day"], "r": float(total), "label": r_multiple(total)})
    return {
        "strategy": body["strategy"],
        "version": body["version"],
        "period": body["period"],
        "out_of_sample_from": body["out_of_sample_from"],
        "full_to_t2": body["full_to_t2"],
        "half_at_t1_breakeven": body["half_at_t1_breakeven"],
        "random_entry_baseline": body["random_entry_baseline"],
        "assumptions": body["assumptions"],
        "caveats": body["caveats"],
        "trades": len(body["trades"]),
        "cumulative_r": curve,
        "report_hash": report.report_hash[:16],
    }


def strategy_tables(markdown: str) -> dict[str, list[list[str]]]:
    """The first pipe table under each `## ` heading of STRATEGY.md, header row included."""
    tables: dict[str, list[list[str]]] = {}
    heading: str | None = None
    for line in markdown.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            continue
        if heading is None or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        tables.setdefault(heading, []).append(cells)
    return tables


def export(settings: Settings, strategy_markdown: str) -> dict[str, Any]:
    settings = demo_settings(settings)
    market = generate_market(settings)
    days = build_days(settings, market)
    tables = strategy_tables(strategy_markdown)
    out_days = []
    for day in days:
        document = compose(day.inputs, day.analysis)
        sections = render_sections(document)
        key, title, summary = DAY_COPY[day.inputs.briefing_date]
        out_days.append(
            {
                "id": key,
                "title": title,
                "summary": summary,
                "briefing_date": day.inputs.briefing_date.isoformat(),
                "date_label": long_day(day.inputs.briefing_date),
                "sent": f"{day.inputs.generated_at.astimezone(MYT):%H:%M} MYT",
                "healthy": document.healthy,
                "setups": [s.symbol for s in document.setups],
                "sections": sections,
                "messages": chunk(sections, TELEGRAM_LIMIT),
            }
        )
    return {
        "label": LABEL,
        "notice": NOTICE,
        "seed": SEED,
        "days": out_days,
        "pipeline": pipeline_story(days[1]),
        "backtest": backtest(settings, market),
        "method": {
            "readiness": tables.get("Readiness", []),
            "quality": tables.get("Bar quality rules", []),
            "rules": tables.get(STRATEGY, []),
            "reviews": tables.get("Holding reviews", []),
            "scorecard": tables.get("Scorecard metrics", []),
        },
        "reasons": {code.value: LABELS[code] for code in ReasonCode if code in LABELS},
        "traces": traces(market),
        "ticker": ticker(days[-1]),
    }


def render_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
