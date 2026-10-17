from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from lens.domain.bars import BarQuality
from lens.domain.evaluation import EventKind, Levels, SignalState, SignalStatus, advance
from tests.helpers import bar, business_days

LEVELS = Levels(Decimal(100), Decimal(95), Decimal("107.5"), Decimal(115))
SIGNAL_DAY = date(2026, 3, 2)


def _run(
    bars: list, state: SignalState | None = None, today: date | None = None, expiry: int = 120
):  # type: ignore[no-untyped-def]
    days = [b.day for b in bars]
    return advance(
        LEVELS,
        state or SignalState(),
        signal_day=SIGNAL_DAY,
        expiry_days=expiry,
        expected_sessions=days,
        bars=bars,
        today=today or (days[-1] if days else SIGNAL_DAY),
    )


def test_bar_touching_stop_and_t2_resolves_stop_first() -> None:
    """Scenario 11."""
    d = date(2026, 3, 3)
    state, events = _run([bar("X", d, "100", "120", "94", "110")])
    assert state.status is SignalStatus.STOPPED
    assert state.exit_price == Decimal(95)
    assert state.outcome_r == Decimal(-1)
    assert [e.kind for e in events] == [EventKind.STOPPED]


def test_gap_below_stop_fills_at_the_open() -> None:
    state, _ = _run([bar("X", date(2026, 3, 3), "90", "91", "89", "90")])
    assert state.exit_price == Decimal(90)
    assert state.outcome_r == Decimal(-2)


def test_t1_then_stop_differs_between_exit_models() -> None:
    days = business_days(date(2026, 3, 3), 3)
    bars = [
        bar("X", days[0], "100", "108", "99", "107"),
        bar("X", days[1], "107", "107", "99", "100"),
        bar("X", days[2], "100", "100", "94", "95"),
    ]
    state, events = _run(bars)
    assert [e.kind for e in events] == [EventKind.T1_TOUCHED, EventKind.STOPPED]
    assert state.status is SignalStatus.STOPPED
    assert state.outcome_r == Decimal(-1)
    # half off at T1 (+1.5R), the rest stopped at breakeven on day 2 (0R)
    assert state.outcome_r_scaled == Decimal("0.75")
    assert state.t1_touched_on == days[0]


def test_t2_hit_marks_t1_on_the_same_bar() -> None:
    state, events = _run([bar("X", date(2026, 3, 3), "101", "116", "99", "114")])
    assert state.status is SignalStatus.T2_HIT
    assert state.outcome_r == Decimal(3)
    assert state.outcome_r_scaled == Decimal("2.25")
    assert [e.kind for e in events] == [EventKind.T1_TOUCHED, EventKind.T2_HIT]


def test_missing_session_pauses_without_skipping_ahead() -> None:
    days = business_days(date(2026, 3, 3), 3)
    bars = [
        bar("X", days[0], "100", "101", "99", "100"),
        bar("X", days[2], "100", "100", "90", "91"),
    ]
    state, events = advance(
        LEVELS,
        SignalState(),
        signal_day=SIGNAL_DAY,
        expiry_days=120,
        expected_sessions=days,
        bars=bars,
        today=days[2],
    )
    assert state.status is SignalStatus.OPEN
    assert state.last_evaluated == days[0]
    assert events[-1].kind is EventKind.PAUSED_DATA_GAP
    assert events[-1].day == days[1]


def test_disputed_bar_also_pauses() -> None:
    disputed = bar("X", date(2026, 3, 3), "100", "100", "90", "91").with_quality(
        BarQuality.DISPUTED
    )
    state, events = _run([disputed])
    assert state.status is SignalStatus.OPEN
    assert events[0].kind is EventKind.PAUSED_DATA_GAP


def test_expiry_closes_at_the_last_close_inside_the_window() -> None:
    days = business_days(date(2026, 3, 3), 4)
    bars = [
        bar("X", d, "100", "102", "99", c)
        for d, c in zip(days, ["101", "102", "103", "104"], strict=True)
    ]
    state, events = advance(
        LEVELS,
        SignalState(),
        signal_day=SIGNAL_DAY,
        expiry_days=(days[2] - SIGNAL_DAY).days,
        expected_sessions=days,
        bars=bars,
        today=days[3],
    )
    assert state.status is SignalStatus.EXPIRED
    assert state.exit_price == Decimal(103)
    assert state.outcome_r == Decimal("0.6")
    assert events[-1].kind is EventKind.EXPIRED


def test_signal_with_no_usable_data_past_grace_is_unverifiable() -> None:
    state, events = advance(
        LEVELS,
        SignalState(),
        signal_day=SIGNAL_DAY,
        expiry_days=10,
        expected_sessions=[],
        bars=[],
        today=SIGNAL_DAY + timedelta(days=30),
    )
    assert state.status is SignalStatus.UNVERIFIABLE
    assert events[0].kind is EventKind.UNVERIFIABLE


def test_resuming_from_state_skips_evaluated_sessions() -> None:
    days = business_days(date(2026, 3, 3), 2)
    bars = [
        bar("X", days[0], "100", "101", "99", "100"),
        bar("X", days[1], "100", "101", "94", "95"),
    ]
    first, _ = advance(
        LEVELS,
        SignalState(),
        signal_day=SIGNAL_DAY,
        expiry_days=120,
        expected_sessions=days[:1],
        bars=bars[:1],
        today=days[0],
    )
    second, events = advance(
        LEVELS,
        first,
        signal_day=SIGNAL_DAY,
        expiry_days=120,
        expected_sessions=days,
        bars=bars,
        today=days[1],
    )
    assert first.status is SignalStatus.OPEN
    assert second.status is SignalStatus.STOPPED
    assert [e.day for e in events] == [days[1]]
