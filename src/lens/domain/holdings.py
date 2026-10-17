"""Daily review of each holding from completed sessions. Reviews suggest; they never instruct."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import IntEnum, StrEnum

from lens.domain.indicators import atr, sma_series
from lens.domain.market_view import MarketView
from lens.domain.money import HUNDRED, to_decimal
from lens.domain.reasons import ReasonCode


class ReviewAction(StrEnum):
    HOLD = "HOLD"
    REVIEW = "REVIEW"
    REDUCE = "REDUCE"
    EXIT = "EXIT"


class _Severity(IntEnum):
    HOLD = 0
    REVIEW = 1
    REDUCE = 2
    EXIT = 3


class MarkStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    DISPUTED = "disputed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class HoldingRules:
    chandelier_atr_multiple: Decimal
    exit_below_ma200_sessions: int
    drawdown_review_pct: Decimal
    max_position_pct: Decimal


@dataclass(frozen=True, slots=True)
class HoldingReview:
    symbol: str
    action: ReviewAction
    reasons: tuple[ReasonCode, ...]
    chandelier_stop: Decimal | None
    peak_close: Decimal | None
    drawdown_pct: Decimal | None


def review_holding(
    view: MarketView,
    *,
    entry_day: date,
    weight_pct: Decimal | None,
    mark_status: MarkStatus,
    rules: HoldingRules,
) -> HoldingReview:
    findings: list[tuple[ReviewAction, ReasonCode]] = []
    if mark_status is MarkStatus.UNAVAILABLE:
        findings.append((ReviewAction.REVIEW, ReasonCode.MARK_UNAVAILABLE))
    elif mark_status is not MarkStatus.FRESH:
        findings.append((ReviewAction.REVIEW, ReasonCode.MARK_STALE))

    chandelier: Decimal | None = None
    peak: Decimal | None = None
    drawdown: Decimal | None = None
    held = view.since(entry_day)
    if len(held) and len(view):
        close = view.last().close
        peak = max(bar.close for bar in held)
        drawdown = (1 - close / peak) * HUNDRED if peak > 0 else None
        average_range = atr(view.highs(), view.lows(), view.closes(), 14)
        if average_range is not None:
            chandelier = peak - to_decimal(average_range) * rules.chandelier_atr_multiple
            if close < chandelier:
                findings.append((ReviewAction.EXIT, ReasonCode.BELOW_CHANDELIER_STOP))
        averages = sma_series(view.closes(), 200)
        recent = list(zip(view.closes(), averages, strict=True))[-rules.exit_below_ma200_sessions :]
        if len(recent) == rules.exit_below_ma200_sessions and all(
            average is not None and value < average for value, average in recent
        ):
            findings.append((ReviewAction.EXIT, ReasonCode.BELOW_MA200))
        if drawdown is not None and drawdown >= rules.drawdown_review_pct:
            findings.append((ReviewAction.REVIEW, ReasonCode.DRAWDOWN_FROM_PEAK))
    if weight_pct is not None and weight_pct > rules.max_position_pct:
        findings.append((ReviewAction.REDUCE, ReasonCode.ABOVE_CONCENTRATION_CAP))

    if not findings:
        return HoldingReview(
            view.symbol, ReviewAction.HOLD, (ReasonCode.HOLDING_OK,), chandelier, peak, drawdown
        )
    action = max((a for a, _ in findings), key=lambda a: _Severity[a.value])
    return HoldingReview(
        view.symbol,
        action,
        tuple(dict.fromkeys(code for _, code in findings)),
        chandelier,
        peak,
        drawdown,
    )
