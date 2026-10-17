"""Walk history one session at a time through the live decision and evaluation code.

Assumptions, stated in every report: entry at the signal session's close; evaluation from the
next session; stop first when a bar touches both; a gap below the stop fills at the open; one
open trade per asset; no fees or slippage; fundamentals are not point-in-time, so the
fundamentals rule is skipped.
"""

from __future__ import annotations

import bisect
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from lens.domain.bars import Bar
from lens.domain.evaluation import Levels, SignalState, SignalStatus, advance
from lens.domain.indicators import atr
from lens.domain.instruments import Instrument
from lens.domain.market_view import MarketView
from lens.domain.money import TickRule
from lens.domain.risk import build_long_setup
from lens.domain.strategy.base import AssetContext, RiskInputs, Setup
from lens.domain.strategy.registry import ConfiguredStrategy

VIEW_SESSIONS = 300

ASSUMPTIONS = (
    "Entry at the signal session's close; evaluation starts the next session.",
    "When one bar touches both the stop and a target, the stop wins.",
    "A gap below the stop fills at that session's open.",
    "One open trade per asset at a time; no fees or slippage.",
    "Fundamentals are not point-in-time, so the fundamentals rule is skipped.",
)


@dataclass(frozen=True, slots=True)
class AssetHistory:
    instrument: Instrument
    bars: tuple[Bar, ...]
    tick_rule: TickRule

    @property
    def days(self) -> list[date]:
        return [b.day for b in self.bars]


@dataclass(frozen=True, slots=True)
class Trade:
    symbol: str
    signal_day: date
    exit_day: date | None
    status: SignalStatus
    entry: Decimal
    outcome_r: Decimal | None
    outcome_r_scaled: Decimal | None
    t1_touched: bool
    mfe_r: Decimal
    mae_r: Decimal
    sessions_held: int


def _view(history: AssetHistory, index: int) -> MarketView:
    start = max(0, index - VIEW_SESSIONS + 1)
    bars = history.bars[start : index + 1]
    return MarketView(history.instrument.symbol, bars[-1].day, bars)


def _follow(
    history: AssetHistory, index: int, levels: Levels, expiry_days: int
) -> tuple[Trade, int]:
    """Evaluate a trade opened at `index` until it ends or history runs out."""
    state = SignalState()
    signal_day = history.bars[index].day
    held = 0
    position = index
    for position in range(index + 1, len(history.bars)):
        bar = history.bars[position]
        state, _ = advance(
            levels,
            state,
            signal_day=signal_day,
            expiry_days=expiry_days,
            expected_sessions=[bar.day],
            bars=[bar],
            today=bar.day,
        )
        held += 1
        if state.terminal:
            break
    trade = Trade(
        history.instrument.symbol,
        signal_day,
        state.exit_day,
        state.status if state.terminal else SignalStatus.OPEN,
        levels.entry,
        state.outcome_r,
        state.outcome_r_scaled,
        state.t1_touched_on is not None,
        state.mfe_r,
        state.mae_r,
        held,
    )
    return trade, position


def run_strategy(
    histories: Sequence[AssetHistory],
    configured: ConfiguredStrategy,
    risk: RiskInputs,
    *,
    start: date,
    end: date,
    min_sessions: int = 200,
) -> list[Trade]:
    trades: list[Trade] = []
    for history in histories:
        ctx = AssetContext(history.instrument, history.tick_rule, risk, None)
        days = history.days
        index = max(bisect.bisect_left(days, start), min_sessions - 1)
        last = bisect.bisect_right(days, end) - 1
        while index <= last:
            decision = configured.strategy.decide(_view(history, index), ctx, configured.params)
            setup = decision.setup
            if setup is None:
                index += 1
                continue
            trade, exit_index = _follow(
                history, index, _levels(setup), configured.params.expiry_days
            )
            trades.append(trade)
            index = exit_index + 1
    return trades


def _levels(setup: Setup) -> Levels:
    return Levels(setup.entry, setup.stop, setup.t1, setup.t2)


def run_random_baseline(
    histories: Sequence[AssetHistory],
    configured: ConfiguredStrategy,
    risk: RiskInputs,
    *,
    start: date,
    end: date,
    trades_per_asset: dict[str, int],
    runs: int = 200,
    seed: int = 11,
    min_sessions: int = 200,
) -> list[Decimal]:
    """Mean outcome per run for random entries with the strategy's own stop and targets."""
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security
    params = configured.params
    t1_r, t2_r = params.targets_r
    means: list[Decimal] = []
    candidates = {}
    for history in histories:
        days = history.days
        first = max(bisect.bisect_left(days, start), min_sessions - 1)
        last = bisect.bisect_right(days, end) - 2
        candidates[history.instrument.symbol] = (history, list(range(first, last + 1)))
    for _ in range(runs):
        outcomes: list[Decimal] = []
        for symbol, count in trades_per_asset.items():
            if symbol not in candidates or not candidates[symbol][1]:
                continue
            history, pool = candidates[symbol]
            for index in sorted(rng.sample(pool, min(count, len(pool)))):
                view = _view(history, index)
                average = atr(view.highs(), view.lows(), view.closes(), params.atr_period)
                if average is None:
                    continue
                setup = build_long_setup(
                    history.bars[index].close,
                    average,
                    stop_multiple=params.atr_stop_multiple,
                    t1_r=t1_r,
                    t2_r=t2_r,
                    min_reward_risk=Decimal(0),
                    risk=risk,
                    tick_rule=history.tick_rule,
                    method="random",
                )
                if not isinstance(setup, Setup):
                    continue
                trade, _ = _follow(history, index, _levels(setup), params.expiry_days)
                if trade.outcome_r is not None:
                    outcomes.append(trade.outcome_r)
        if outcomes:
            means.append(sum(outcomes, Decimal(0)) / len(outcomes))
    return means


def buy_and_hold_pct(history: AssetHistory, start: date, end: date) -> Decimal | None:
    window = [b for b in history.bars if start <= b.day <= end]
    if len(window) < 2 or window[0].close <= 0:
        return None
    return ((window[-1].close / window[0].close - 1) * 100).quantize(Decimal("0.1"))
