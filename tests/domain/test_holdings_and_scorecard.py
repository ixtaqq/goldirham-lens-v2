from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from lens.domain.evaluation import SignalStatus
from lens.domain.holdings import HoldingRules, MarkStatus, ReviewAction, review_holding
from lens.domain.market_view import MarketView
from lens.domain.reasons import ReasonCode
from lens.domain.scorecard import ExitModel, SignalRecord, bootstrap_interval, build_scorecard
from tests.helpers import make_bars

RULES = HoldingRules(Decimal(3), 3, Decimal(25), Decimal(20))


def _view(closes: list[float]) -> MarketView:
    return MarketView.of(
        "SPY", make_bars("SPY", closes, start=date(2025, 1, 2), spread="0.002"), date(2030, 1, 1)
    )


def test_healthy_uptrend_holds() -> None:
    view = _view([100 * 1.002**i for i in range(260)])
    review = review_holding(
        view,
        entry_day=view.days()[200],
        weight_pct=Decimal(10),
        mark_status=MarkStatus.FRESH,
        rules=RULES,
    )
    assert review.action is ReviewAction.HOLD
    assert review.reasons == (ReasonCode.HOLDING_OK,)


def test_break_below_trailing_stop_and_ma200_suggests_exit() -> None:
    closes = [100 * 1.002**i for i in range(240)] + [100.0 * 0.9**i for i in range(1, 8)]
    view = _view(closes)
    review = review_holding(
        view,
        entry_day=view.days()[220],
        weight_pct=Decimal(5),
        mark_status=MarkStatus.FRESH,
        rules=RULES,
    )
    assert review.action is ReviewAction.EXIT
    assert ReasonCode.BELOW_CHANDELIER_STOP in review.reasons
    assert ReasonCode.BELOW_MA200 in review.reasons
    assert ReasonCode.DRAWDOWN_FROM_PEAK in review.reasons


def test_oversized_position_suggests_reduce_and_stale_mark_review() -> None:
    view = _view([100 * 1.002**i for i in range(260)])
    oversized = review_holding(
        view,
        entry_day=view.days()[0],
        weight_pct=Decimal(35),
        mark_status=MarkStatus.FRESH,
        rules=RULES,
    )
    assert oversized.action is ReviewAction.REDUCE
    stale = review_holding(
        view,
        entry_day=view.days()[0],
        weight_pct=Decimal(5),
        mark_status=MarkStatus.STALE,
        rules=RULES,
    )
    assert stale.action is ReviewAction.REVIEW
    assert stale.reasons == (ReasonCode.MARK_STALE,)


def _record(
    i: int, status: SignalStatus, r: str | None, t1: bool = False, scaled: str | None = None
) -> SignalRecord:
    day = date(2026, 1, 1) + timedelta(days=i)
    return SignalRecord(
        day,
        status,
        t1,
        None if r is None else Decimal(r),
        None if scaled is None else Decimal(scaled),
        day + timedelta(days=10),
        Decimal(1),
        Decimal(-1),
    )


def test_small_samples_show_counts_only() -> None:
    records = [_record(i, SignalStatus.T2_HIT, "3", True) for i in range(5)] + [
        _record(9, SignalStatus.OPEN, None)
    ]
    card = build_scorecard(
        records,
        as_of=date(2026, 6, 1),
        window_days=365,
        min_sample=20,
        exit_model=ExitModel.FULL_TO_T2,
    )
    assert not card.sufficient
    assert (card.resolved, card.open) == (5, 1)
    assert card.expectancy is None
    assert card.win_rate is None


def test_hand_computed_scorecard() -> None:
    """20 resolved: 8 T2 (+3R, T1 touched), 2 stopped after T1 (-1R), 10 stopped (-1R).

    Expectancy full_to_t2 = (8*3 - 12) / 20 = 0.60R. T1-touch rate = 10/20 = 50%. Win rate 40%.
    """
    records = (
        [_record(i, SignalStatus.T2_HIT, "3", True, "2.25") for i in range(8)]
        + [_record(10 + i, SignalStatus.STOPPED, "-1", True, "0.75") for i in range(2)]
        + [_record(20 + i, SignalStatus.STOPPED, "-1") for i in range(10)]
        + [_record(40, SignalStatus.UNVERIFIABLE, None)]
    )
    card = build_scorecard(
        records,
        as_of=date(2026, 6, 1),
        window_days=365,
        min_sample=20,
        exit_model=ExitModel.FULL_TO_T2,
    )
    assert card.sufficient
    assert card.resolved == 20
    assert card.unverifiable == 1
    assert card.expectancy == Decimal("0.60")
    assert card.t1_touch_rate == Decimal("50.0")
    assert card.win_rate == Decimal("40.0")
    assert card.ci_low is not None
    assert card.ci_high is not None
    assert card.ci_low < card.expectancy < card.ci_high
    assert card.median_hold_days == 10

    scaled = build_scorecard(
        records,
        as_of=date(2026, 6, 1),
        window_days=365,
        min_sample=20,
        exit_model=ExitModel.HALF_AT_T1_BREAKEVEN,
    )
    # (8*2.25 + 2*0.75 - 10) / 20 = 0.475 -> 0.48 (banker's rounding keeps 0.48)
    assert scaled.expectancy == Decimal("0.48")
    assert scaled.win_rate == Decimal("50.0")


def test_window_excludes_old_signals() -> None:
    old = [_record(-400 + i, SignalStatus.T2_HIT, "3", True) for i in range(25)]
    card = build_scorecard(
        old, as_of=date(2026, 6, 1), window_days=365, min_sample=20, exit_model=ExitModel.FULL_TO_T2
    )
    assert card.resolved == 0


def test_interval_bound_that_rounds_to_zero_has_no_sign() -> None:
    low, high = bootstrap_interval([Decimal("-0.001"), Decimal("0.001")])
    assert (str(low), str(high)) == ("0.00", "0.00")
