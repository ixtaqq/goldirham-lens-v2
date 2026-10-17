from __future__ import annotations

from datetime import date
from decimal import Decimal

from lens.domain.bars import BarQuality
from lens.domain.readiness import assess_readiness
from lens.domain.reasons import ReasonCode
from lens.domain.validation import QualityInputs, assess
from tests.helpers import bar, business_days, make_bars


def _inputs(**overrides: object) -> QualityInputs:
    values: dict[str, object] = {
        "jump_threshold_pct": Decimal(20),
        "cross_check_tolerance_pct": Decimal(2),
        "cross_check_days": frozenset(),
        "cross_check_closes": {},
        "cross_check_available": True,
        "confirmed_splits": {},
    }
    values.update(overrides)
    return QualityInputs(**values)  # type: ignore[arg-type]


def test_split_sized_move_without_a_confirmed_action_is_quarantined() -> None:
    bars = make_bars("NVDA", [400, 402, 100.5, 101])
    result = assess(bars, _inputs())
    assert [b.quality for b in result] == [
        BarQuality.VERIFIED,
        BarQuality.VERIFIED,
        BarQuality.CORPORATE_ACTION_PENDING,
        BarQuality.VERIFIED,
    ]


def test_confirmed_split_clears_the_quarantine() -> None:
    bars = make_bars("NVDA", [400, 402, 100.5])
    result = assess(bars, _inputs(confirmed_splits={bars[2].day: Decimal(4)}))
    assert result[2].quality is BarQuality.VERIFIED


def test_crypto_halving_is_never_read_as_a_split() -> None:
    days = business_days(date(2026, 1, 5), 3)
    confirmed = [
        bar("SOL-USD", days[0], "200", "202", "198", "200", "5000"),
        bar("SOL-USD", days[1], "200", "202", "198", "201", "5000"),
        bar("SOL-USD", days[2], "201", "201", "99", "100", "9000"),
    ]
    thin = [*confirmed[:2], bar("SOL-USD", days[2], "201", "201", "99", "100", "10")]
    crypto = _inputs(splits_possible=False, jump_threshold_pct=Decimal(35))

    assert assess(confirmed, crypto)[2].quality is BarQuality.VERIFIED
    assert assess(thin, crypto)[2].quality is BarQuality.SUSPECT


def test_large_move_on_thin_volume_is_suspect() -> None:
    days = business_days(date(2026, 1, 5), 3)
    bars = [
        bar("AAPL", days[0], "100", "101", "99", "100", "1000000"),
        bar("AAPL", days[1], "100", "101", "99", "100", "1000000"),
        bar("AAPL", days[2], "100", "131", "100", "130", "100"),
    ]
    assert assess(bars, _inputs())[2].quality is BarQuality.SUSPECT


def test_broken_ohlc_is_invalid() -> None:
    bad = bar("AAPL", date(2026, 1, 5), "100", "99", "98", "100")
    result = assess([bad], _inputs())
    assert result[0].quality is BarQuality.INVALID
    assert result[0].reasons == (ReasonCode.INVALID_BAR,)


def test_cross_check_disagreement_over_tolerance_is_disputed() -> None:
    """Scenario 3: a 3% close difference becomes disputed."""
    bars = make_bars("MSFT", [400, 401, 402])
    last = bars[-1].day
    result = assess(
        bars,
        _inputs(cross_check_days=frozenset({last}), cross_check_closes={last: Decimal("390.0")}),
    )
    assert result[-1].quality is BarQuality.DISPUTED
    agreeing = assess(
        bars,
        _inputs(cross_check_days=frozenset({last}), cross_check_closes={last: Decimal("401.0")}),
    )
    assert agreeing[-1].quality is BarQuality.VERIFIED


def test_missing_cross_check_marks_recent_bars_single_source() -> None:
    bars = make_bars("1155.KL", [9.5, 9.6])
    result = assess(
        bars, _inputs(cross_check_days=frozenset({bars[-1].day}), cross_check_available=False)
    )
    assert result[-1].quality is BarQuality.SINGLE_SOURCE


def test_market_holiday_is_not_a_missing_session() -> None:
    """Scenario 1: the calendar omits the holiday, so readiness stays ready."""
    days = [d for d in business_days(date(2026, 1, 1), 205) if d != date(2026, 2, 17)]
    bars = make_bars("1155.KL", [10.0] * len(days), days=days)
    readiness = assess_readiness(bars, days[-200:], single_source_allowed=True)
    assert readiness.ready
    assert readiness.latest_session == days[-1]


def test_stale_missing_and_insufficient_history_are_reported() -> None:
    days = business_days(date(2026, 1, 1), 210)
    bars = make_bars("AAPL", [100.0] * 209, days=days[:209])
    stale = assess_readiness(bars, days[-200:], single_source_allowed=False)
    assert ReasonCode.STALE_SESSION in stale.reasons

    gapped = [b for b in make_bars("AAPL", [100.0] * 210, days=days) if b.day != days[150]]
    missing = assess_readiness(gapped, days[-200:], single_source_allowed=False)
    assert missing.reasons == (ReasonCode.MISSING_SESSION,)

    short = make_bars("AAPL", [100.0] * 50, days=days[-50:])
    assert (
        ReasonCode.INSUFFICIENT_HISTORY
        in assess_readiness(short, days[-200:], single_source_allowed=False).reasons
    )
    assert assess_readiness([], days[-200:], single_source_allowed=False).reasons == (
        ReasonCode.NO_COMPLETED_HISTORY,
    )


def test_recent_single_source_bar_blocks_only_where_not_allowed() -> None:
    days = business_days(date(2026, 1, 1), 200)
    bars = make_bars("AAPL", [100.0] * 200, days=days)
    bars[-1] = bars[-1].with_quality(BarQuality.SINGLE_SOURCE, ReasonCode.SINGLE_SOURCE_UNVERIFIED)
    assert assess_readiness(bars, days, single_source_allowed=False).reasons == (
        ReasonCode.SINGLE_SOURCE_UNVERIFIED,
    )
    assert assess_readiness(bars, days, single_source_allowed=True).ready


def test_disputed_bar_inside_the_window_blocks_readiness() -> None:
    days = business_days(date(2026, 1, 1), 200)
    bars = make_bars("MSFT", [100.0] * 200, days=days)
    bars[100] = bars[100].with_quality(BarQuality.DISPUTED, ReasonCode.DISPUTED_BAR)
    assert assess_readiness(bars, days, single_source_allowed=False).reasons == (
        ReasonCode.DISPUTED_BAR,
    )
