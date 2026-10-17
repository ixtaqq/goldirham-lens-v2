"""Bar quality rules. Each rule is a pure function; `assess` applies them in order."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from lens.domain.bars import Bar, BarQuality
from lens.domain.money import HUNDRED
from lens.domain.reasons import ReasonCode

SPLIT_RATIOS: tuple[Decimal, ...] = tuple(
    Decimal(r)
    for r in ("2", "3", "4", "5", "10", "1.5", "0.5", "0.3333333333", "0.25", "0.2", "0.1")
)
SPLIT_TOLERANCE = Decimal("0.01")


def shape_is_valid(bar: Bar) -> bool:
    values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
    if not all(value.is_finite() for value in values):
        return False
    if bar.low <= 0 or bar.volume < 0:
        return False
    return bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high


def jump_pct(previous_close: Decimal, close: Decimal) -> Decimal:
    return abs(close / previous_close - 1) * HUNDRED


def is_suspect_jump(
    previous_close: Decimal,
    bar: Bar,
    *,
    threshold_pct: Decimal,
    average_volume: Decimal | None,
) -> bool:
    """A large move without volume confirmation (volume under half its recent average)."""
    if jump_pct(previous_close, bar.close) <= threshold_pct:
        return False
    if average_volume is None or average_volume <= 0 or bar.volume <= 0:
        return True
    return bar.volume < average_volume / 2


def split_ratio(previous_close: Decimal, close: Decimal) -> Decimal | None:
    """Return the split ratio a price change matches, e.g. 4 for a 4:1 split."""
    move = previous_close / close
    for ratio in SPLIT_RATIOS:
        if abs(move / ratio - 1) <= SPLIT_TOLERANCE:
            return ratio
    return None


def closes_disagree(primary: Decimal, secondary: Decimal, *, tolerance_pct: Decimal) -> bool:
    return abs(primary / secondary - 1) * HUNDRED > tolerance_pct


@dataclass(frozen=True, slots=True)
class QualityInputs:
    jump_threshold_pct: Decimal
    cross_check_tolerance_pct: Decimal
    cross_check_days: frozenset[date]
    cross_check_closes: Mapping[date, Decimal]
    cross_check_available: bool
    confirmed_splits: Mapping[date, Decimal]
    splits_possible: bool = True


def assess(bars: Sequence[Bar], inputs: QualityInputs) -> list[Bar]:
    """Assign a quality to each bar, oldest first. Earlier bars inform later checks."""
    assessed: list[Bar] = []
    previous: Bar | None = None
    volumes: list[Decimal] = []
    for bar in sorted(bars, key=lambda b: b.day):
        result = bar
        if not shape_is_valid(bar):
            result = bar.with_quality(BarQuality.INVALID, ReasonCode.INVALID_BAR)
        elif previous is not None and previous.close > 0:
            ratio = split_ratio(previous.close, bar.close) if inputs.splits_possible else None
            confirmed = inputs.confirmed_splits.get(bar.day)
            average = sum(volumes[-20:], Decimal(0)) / len(volumes[-20:]) if volumes else None
            if ratio is not None and confirmed is None:
                result = bar.with_quality(
                    BarQuality.CORPORATE_ACTION_PENDING, ReasonCode.CORPORATE_ACTION_PENDING
                )
            elif confirmed is None and is_suspect_jump(
                previous.close, bar, threshold_pct=inputs.jump_threshold_pct, average_volume=average
            ):
                result = bar.with_quality(BarQuality.SUSPECT, ReasonCode.SUSPECT_BAR)
        if result.quality is BarQuality.VERIFIED and bar.day in inputs.cross_check_days:
            secondary = inputs.cross_check_closes.get(bar.day)
            if secondary is None or not inputs.cross_check_available:
                result = result.with_quality(
                    BarQuality.SINGLE_SOURCE, ReasonCode.SINGLE_SOURCE_UNVERIFIED
                )
            elif closes_disagree(
                bar.close, secondary, tolerance_pct=inputs.cross_check_tolerance_pct
            ):
                result = result.with_quality(BarQuality.DISPUTED, ReasonCode.DISPUTED_BAR)
        assessed.append(result)
        if result.quality is not BarQuality.INVALID:
            previous = result
            volumes.append(result.volume)
    return assessed
