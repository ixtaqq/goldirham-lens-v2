"""Pure analysis of one cycle's inputs: decisions, signal progress, marks, portfolio, reviews."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from lens.domain.bars import Bar
from lens.domain.briefing import BenchmarkLine, Regime
from lens.domain.evaluation import Event, SignalState, advance
from lens.domain.holdings import HoldingReview, HoldingRules, MarkStatus, review_holding
from lens.domain.indicators import IndicatorSet, compute_indicators
from lens.domain.instruments import Market
from lens.domain.market_view import MarketView
from lens.domain.money import HUNDRED
from lens.domain.portfolio import (
    FxRate,
    Mark,
    PortfolioSnapshot,
    Position,
    build_positions,
    value_portfolio,
)
from lens.domain.reasons import ReasonCode
from lens.domain.strategy.base import AssetContext, Decision, Fundamentals, RiskInputs
from lens.domain.strategy.registry import ConfiguredStrategy, configure
from lens.pipeline.inputs import AssetIn, CycleInputs, SignalIn
from lens.settings import Settings

MAX_SETUPS = 3


@dataclass(frozen=True, slots=True)
class AssetAnalysis:
    asset: AssetIn
    bars: tuple[Bar, ...]
    indicators: IndicatorSet | None
    decisions: tuple[Decision, ...]
    latest: Bar | None
    change_pct: Decimal | None
    above_ma200: bool | None

    @property
    def ready(self) -> bool:
        return not self.asset.readiness


@dataclass(frozen=True, slots=True)
class SignalUpdate:
    signal: SignalIn
    state: SignalState
    events: tuple[Event, ...]


@dataclass(frozen=True, slots=True)
class Analysis:
    settings: Settings
    strategies: tuple[ConfiguredStrategy, ...]
    assets: dict[str, AssetAnalysis]
    signal_updates: tuple[SignalUpdate, ...]
    setups: tuple[Decision, ...]
    marks: dict[str, Mark]
    positions: dict[str, Position]
    portfolio: PortfolioSnapshot | None
    reviews: dict[str, HoldingReview]
    benchmarks: tuple[BenchmarkLine, ...]
    breadth_pct: Decimal | None
    regime: Regime


def _usable(bars: tuple[Bar, ...]) -> list[Bar]:
    return [b for b in bars if b.usable]


def _change_pct(usable: list[Bar]) -> Decimal | None:
    if len(usable) < 2 or usable[-2].close <= 0:
        return None
    return ((usable[-1].close / usable[-2].close - 1) * HUNDRED).quantize(Decimal("0.01"))


def _mark(asset: AssetIn, bars: tuple[Bar, ...]) -> Mark:
    usable = _usable(bars)
    if not usable:
        return Mark(None, None, None, MarkStatus.UNAVAILABLE)
    expected = asset.closed_sessions[-1] if asset.closed_sessions else None
    latest_any = bars[-1]
    last_good = usable[-1]
    if latest_any.day == expected and latest_any.usable:
        status = MarkStatus.FRESH
    elif latest_any.day == expected:
        status = MarkStatus.DISPUTED
    else:
        status = MarkStatus.STALE
    return Mark(last_good.close, last_good.day, last_good.provider, status)


def _analyze_asset(
    asset: AssetIn,
    strategies: tuple[ConfiguredStrategy, ...],
    settings: Settings,
    risk: RiskInputs,
    fundamentals: dict[str, Fundamentals],
) -> AssetAnalysis:
    bars = tuple(asset.domain_bars())
    usable = _usable(bars)
    session = (
        asset.closed_sessions[-1] if asset.closed_sessions else (bars[-1].day if bars else date.min)
    )
    view = MarketView.of(asset.symbol, usable, as_of=session) if usable else None
    periods = 365 if asset.market is Market.CRYPTO_UTC else 252
    indicators = (
        compute_indicators(view, periods_per_year=periods)
        if view is not None and len(view)
        else None
    )
    decisions: list[Decision] = []
    if asset.watched:
        ctx = AssetContext(
            asset.instrument(),
            settings.tick_rule(asset.market),
            risk,
            fundamentals.get(asset.symbol),
        )
        for configured in strategies:
            if not configured.enabled:
                continue
            if asset.readiness or view is None:
                decisions.append(
                    Decision(
                        asset.symbol,
                        session,
                        configured.name,
                        configured.version,
                        asset.readiness or (ReasonCode.NO_COMPLETED_HISTORY,),
                        None,
                        indicators.as_dict() if indicators else {},
                    )
                )
            else:
                decisions.append(configured.strategy.decide(view, ctx, configured.params))
    above = None
    if indicators is not None and indicators.sma200 is not None:
        above = indicators.close > indicators.sma200
    return AssetAnalysis(
        asset,
        bars,
        indicators,
        tuple(decisions),
        usable[-1] if usable else None,
        _change_pct(usable),
        above,
    )


def strategies_from(settings: Settings) -> tuple[ConfiguredStrategy, ...]:
    return tuple(
        configure(
            {name: (entry.enabled, entry.params) for name, entry in settings.strategies.items()}
        )
    )


def analyze(inputs: CycleInputs) -> Analysis:
    settings = Settings.model_validate(inputs.settings)
    strategies = strategies_from(settings)
    risk = RiskInputs(inputs.risk_per_trade_pct, settings.risk.max_position_pct)
    fundamentals = {f.symbol: f.fundamentals() for f in inputs.fundamentals}
    assets = {
        a.symbol: _analyze_asset(a, strategies, settings, risk, fundamentals) for a in inputs.assets
    }

    updates: list[SignalUpdate] = []
    for signal in inputs.signals:
        analysed = assets.get(signal.symbol)
        if analysed is None:
            continue
        state, events = advance(
            signal.levels(),
            signal.state(),
            signal_day=signal.signal_day,
            expiry_days=signal.expiry_days,
            expected_sessions=analysed.asset.closed_sessions,
            bars=analysed.bars,
            today=inputs.briefing_date,
        )
        if events or state != signal.state():
            updates.append(SignalUpdate(signal, state, tuple(events)))

    transactions = [t.transaction() for t in inputs.transactions]
    positions = build_positions(transactions)
    held = {s for s, p in positions.items() if p.quantity > 0}
    marks = {s: _mark(assets[s].asset, assets[s].bars) for s in held if s in assets}
    fx: dict[str, FxRate] = {}
    for rate in sorted(inputs.fx, key=lambda r: r.day):
        if rate.day <= inputs.briefing_date:
            fx[rate.quote] = rate.fx()
    portfolio = None
    if held:
        portfolio = value_portfolio(
            {s: p for s, p in positions.items() if s in held},
            asset_classes={s: a.asset.asset_class for s, a in assets.items()},
            marks=marks,
            fx=fx,
            base_currency=inputs.base_currency,
        )

    rules = HoldingRules(
        settings.holdings.chandelier_atr_multiple,
        settings.holdings.exit_below_ma200_sessions,
        settings.holdings.drawdown_review_pct,
        settings.risk.max_position_pct,
    )
    reviews: dict[str, HoldingReview] = {}
    if portfolio is not None:
        for holding in portfolio.holdings:
            analysed = assets.get(holding.symbol)
            if analysed is None or holding.opened is None:
                continue
            usable = _usable(analysed.bars)
            view = MarketView.of(holding.symbol, usable, as_of=inputs.briefing_date)
            reviews[holding.symbol] = review_holding(
                view,
                entry_day=holding.opened,
                weight_pct=holding.weight_pct,
                mark_status=holding.mark.status,
                rules=rules,
            )

    exposure = portfolio.exposure_by_asset_class if portfolio else {}
    for symbol, analysed in list(assets.items()):
        cap = settings.risk.max_asset_class_pct.get(analysed.asset.asset_class)
        if cap is not None and exposure.get(analysed.asset.asset_class, Decimal(0)) >= cap:
            capped = tuple(_with_cap_reason(d) if d.setup else d for d in analysed.decisions)
            assets[symbol] = replace(analysed, decisions=capped)
    live = {s.version for s in strategies if s.enabled and s.version in inputs.active_versions}
    setups = sorted(
        (
            d
            for a in assets.values()
            for d in a.decisions
            if d.setup is not None and d.strategy_version in live
        ),
        key=lambda d: (-(d.setup.reward_risk if d.setup else Decimal(0)), d.symbol),
    )

    benchmarks: list[BenchmarkLine] = []
    for symbol in settings.benchmarks.values():
        analysed = assets.get(symbol)
        if analysed is None or analysed.latest is None:
            continue
        benchmarks.append(
            BenchmarkLine(
                symbol=symbol,
                name=analysed.asset.name,
                currency=analysed.asset.currency,
                session=analysed.latest.day,
                close=analysed.latest.close,
                change_pct=analysed.change_pct,
                above_ma200=analysed.above_ma200,
            )
        )
    ready = [
        a for a in assets.values() if a.asset.watched and a.ready and a.above_ma200 is not None
    ]
    breadth = (
        (Decimal(sum(bool(a.above_ma200) for a in ready)) / len(ready) * HUNDRED).quantize(
            Decimal("0.1")
        )
        if ready
        else None
    )
    us = next((b for b in benchmarks if b.symbol == settings.benchmarks.get(Market.XNYS)), None)
    regime: Regime = "unknown"
    if us is not None and us.above_ma200 is not None and breadth is not None:
        if us.above_ma200 and breadth >= 50:
            regime = "risk_on"
        elif not us.above_ma200 and breadth < 50:
            regime = "risk_off"
        else:
            regime = "neutral"

    return Analysis(
        settings=settings,
        strategies=strategies,
        assets=assets,
        signal_updates=tuple(updates),
        setups=tuple(setups[:MAX_SETUPS]),
        marks=marks,
        positions=positions,
        portfolio=portfolio,
        reviews=reviews,
        benchmarks=tuple(benchmarks),
        breadth_pct=breadth,
        regime=regime,
    )


def _with_cap_reason(decision: Decision) -> Decision:
    return replace(
        decision, setup=None, reasons=(*decision.reasons, ReasonCode.ASSET_CLASS_CAP_REACHED)
    )
