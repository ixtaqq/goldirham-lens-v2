"""Signal outcome metrics with written definitions. No confidence scores, ever."""

from __future__ import annotations

import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from lens.domain.evaluation import SignalStatus


class ExitModel(StrEnum):
    FULL_TO_T2 = "full_to_t2"
    HALF_AT_T1_BREAKEVEN = "half_at_t1_breakeven"


DEFINITIONS: dict[str, str] = {
    "t1_touch_rate": "Share of resolved signals whose price reached T1 at any point.",
    "win_rate": (
        "Share of resolved signals whose final outcome was above 0R under the named exit model."
    ),
    "expectancy": "Mean outcome in R per resolved signal under the named exit model.",
    "ci": "90% bootstrap interval for expectancy (2,000 resamples, fixed seed).",
    "median_hold_days": "Median calendar days from signal to exit for resolved signals.",
    "resolved": "Signals that stopped, hit T2, or expired with a verified price.",
    "unverifiable": "Signals that could not be evaluated past expiry; counted, not rated.",
}


@dataclass(frozen=True, slots=True)
class SignalRecord:
    signal_day: date
    status: SignalStatus
    t1_touched: bool
    outcome_r: Decimal | None
    outcome_r_scaled: Decimal | None
    exit_day: date | None
    mfe_r: Decimal
    mae_r: Decimal


@dataclass(frozen=True, slots=True)
class Scorecard:
    exit_model: ExitModel
    window_start: date
    window_end: date
    resolved: int
    open: int
    unverifiable: int
    sufficient: bool
    t1_touch_rate: Decimal | None
    win_rate: Decimal | None
    expectancy: Decimal | None
    ci_low: Decimal | None
    ci_high: Decimal | None
    median_hold_days: int | None
    mfe_quartiles: tuple[Decimal, Decimal, Decimal] | None
    mae_quartiles: tuple[Decimal, Decimal, Decimal] | None


def _quartiles(values: Sequence[Decimal]) -> tuple[Decimal, Decimal, Decimal] | None:
    if len(values) < 4:
        return None
    q = statistics.quantiles(values, n=4, method="inclusive")
    return (q[0], q[1], q[2])


def bootstrap_interval(
    values: Sequence[Decimal], *, seed: int = 7, resamples: int = 2000
) -> tuple[Decimal, Decimal]:
    rng = random.Random(seed)  # noqa: S311 - reproducible resampling
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(resamples))
    low = means[int(0.05 * resamples)]
    high = means[int(0.95 * resamples) - 1]
    return _cents(low), _cents(high)


def _cents(value: Decimal | float) -> Decimal:
    """Round to 0.01R. A bound that rounds to zero is plain 0.00, never -0.00."""
    rounded = Decimal(value).quantize(Decimal("0.01"))
    return abs(rounded) if rounded == 0 else rounded


def build_scorecard(
    records: Sequence[SignalRecord],
    *,
    as_of: date,
    window_days: int,
    min_sample: int,
    exit_model: ExitModel,
) -> Scorecard:
    start = as_of - timedelta(days=window_days)
    in_window = [r for r in records if start <= r.signal_day <= as_of]
    resolved = [
        r
        for r in in_window
        if r.status in (SignalStatus.STOPPED, SignalStatus.T2_HIT, SignalStatus.EXPIRED)
        and r.outcome_r is not None
    ]
    open_count = sum(r.status is SignalStatus.OPEN for r in in_window)
    unverifiable = sum(r.status is SignalStatus.UNVERIFIABLE for r in in_window)
    sufficient = len(resolved) >= min_sample
    if not sufficient:
        return Scorecard(
            exit_model,
            start,
            as_of,
            len(resolved),
            open_count,
            unverifiable,
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )

    def outcome(r: SignalRecord) -> Decimal:
        if exit_model is ExitModel.HALF_AT_T1_BREAKEVEN and r.outcome_r_scaled is not None:
            return r.outcome_r_scaled
        assert r.outcome_r is not None
        return r.outcome_r

    outcomes = [outcome(r) for r in resolved]
    n = Decimal(len(resolved))
    hundred = Decimal(100)
    low, high = bootstrap_interval(outcomes)
    holds = [(r.exit_day - r.signal_day).days for r in resolved if r.exit_day is not None]
    return Scorecard(
        exit_model=exit_model,
        window_start=start,
        window_end=as_of,
        resolved=len(resolved),
        open=open_count,
        unverifiable=unverifiable,
        sufficient=True,
        t1_touch_rate=(Decimal(sum(r.t1_touched for r in resolved)) / n * hundred).quantize(
            Decimal("0.1")
        ),
        win_rate=(Decimal(sum(o > 0 for o in outcomes)) / n * hundred).quantize(Decimal("0.1")),
        expectancy=(sum(outcomes, Decimal(0)) / n).quantize(Decimal("0.01")),
        ci_low=low,
        ci_high=high,
        median_hold_days=int(statistics.median(holds)) if holds else None,
        mfe_quartiles=_quartiles([r.mfe_r for r in resolved]),
        mae_quartiles=_quartiles([r.mae_r for r in resolved]),
    )
