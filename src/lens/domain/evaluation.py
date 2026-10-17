"""Signal outcome tracking over completed sessions, in order, one session at a time.

Entry is the signal session's close. Evaluation starts with the next session. When one bar
touches both the stop and a target, the stop wins. A gap below the stop fills at the open.
Two exit models run side by side so the scorecard can name the one it reports.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from lens.domain.bars import Bar

UNVERIFIABLE_GRACE = timedelta(days=7)
HALF = Decimal("0.5")


class SignalStatus(StrEnum):
    OPEN = "OPEN"
    STOPPED = "STOPPED"
    T2_HIT = "T2_HIT"
    EXPIRED = "EXPIRED"
    UNVERIFIABLE = "UNVERIFIABLE"


TERMINAL = frozenset(
    {SignalStatus.STOPPED, SignalStatus.T2_HIT, SignalStatus.EXPIRED, SignalStatus.UNVERIFIABLE}
)


class EventKind(StrEnum):
    T1_TOUCHED = "T1_TOUCHED"
    STOPPED = "STOPPED"
    T2_HIT = "T2_HIT"
    EXPIRED = "EXPIRED"
    PAUSED_DATA_GAP = "PAUSED_DATA_GAP"
    UNVERIFIABLE = "UNVERIFIABLE"


@dataclass(frozen=True, slots=True)
class Levels:
    entry: Decimal
    stop: Decimal
    t1: Decimal
    t2: Decimal

    @property
    def r_unit(self) -> Decimal:
        return self.entry - self.stop

    def r(self, price: Decimal) -> Decimal:
        return (price - self.entry) / self.r_unit


@dataclass(frozen=True, slots=True)
class SignalState:
    status: SignalStatus = SignalStatus.OPEN
    last_evaluated: date | None = None
    t1_touched_on: date | None = None
    exit_day: date | None = None
    exit_price: Decimal | None = None
    outcome_r: Decimal | None = None
    outcome_r_scaled: Decimal | None = None
    mfe_r: Decimal = Decimal(0)
    mae_r: Decimal = Decimal(0)
    last_close: Decimal | None = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL


@dataclass(frozen=True, slots=True)
class Event:
    kind: EventKind
    day: date
    price: Decimal | None
    r: Decimal | None


def _scaled_r(levels: Levels, t1_touched: bool, final_price: Decimal) -> Decimal:
    """Half exits at T1; the rest exits at `final_price`."""
    if not t1_touched:
        return levels.r(final_price)
    return HALF * levels.r(levels.t1) + HALF * levels.r(final_price)


def advance(
    levels: Levels,
    state: SignalState,
    *,
    signal_day: date,
    expiry_days: int,
    expected_sessions: Sequence[date],
    bars: Sequence[Bar],
    today: date,
) -> tuple[SignalState, list[Event]]:
    """Process closed sessions after `state.last_evaluated` (or after `signal_day`).

    `expected_sessions` is the calendar's closed sessions, oldest first. A missing or unusable
    bar pauses evaluation at that session until it is repaired.
    """
    if state.terminal:
        return state, []
    if levels.r_unit <= 0:
        raise ValueError("stop must be below entry")
    by_day = {bar.day: bar for bar in bars}
    start_after = state.last_evaluated or signal_day
    events: list[Event] = []
    expiry_day = signal_day + timedelta(days=expiry_days)
    for day in expected_sessions:
        if day <= start_after:
            continue
        if day > expiry_day:
            price = state.last_close if state.last_close is not None else levels.entry
            exit_day = state.last_evaluated or signal_day
            state = replace(
                state,
                status=SignalStatus.EXPIRED,
                exit_day=exit_day,
                exit_price=price,
                outcome_r=levels.r(price),
                outcome_r_scaled=(
                    state.outcome_r_scaled
                    if state.outcome_r_scaled is not None
                    else _scaled_r(levels, state.t1_touched_on is not None, price)
                ),
            )
            events.append(Event(EventKind.EXPIRED, exit_day, price, state.outcome_r))
            return state, events
        bar = by_day.get(day)
        if bar is None or not bar.usable:
            events.append(Event(EventKind.PAUSED_DATA_GAP, day, None, None))
            break
        state = replace(
            state,
            mfe_r=max(state.mfe_r, levels.r(bar.high)),
            mae_r=min(state.mae_r, levels.r(bar.low)),
        )
        breakeven_active = state.t1_touched_on is not None
        if bar.low <= levels.stop:
            fill = min(bar.open, levels.stop)
            state = replace(
                state,
                status=SignalStatus.STOPPED,
                last_evaluated=day,
                exit_day=day,
                exit_price=fill,
                outcome_r=levels.r(fill),
                outcome_r_scaled=(
                    state.outcome_r_scaled
                    if state.outcome_r_scaled is not None
                    else _scaled_r(levels, True, min(bar.open, levels.entry))
                    if breakeven_active
                    else levels.r(fill)
                ),
            )
            events.append(Event(EventKind.STOPPED, day, fill, state.outcome_r))
            return state, events
        if breakeven_active and state.outcome_r_scaled is None and bar.low <= levels.entry:
            state = replace(
                state, outcome_r_scaled=_scaled_r(levels, True, min(bar.open, levels.entry))
            )
        if bar.high >= levels.t2:
            state = replace(
                state,
                status=SignalStatus.T2_HIT,
                last_evaluated=day,
                exit_day=day,
                exit_price=levels.t2,
                outcome_r=levels.r(levels.t2),
                outcome_r_scaled=(
                    state.outcome_r_scaled
                    if state.outcome_r_scaled is not None
                    else _scaled_r(levels, True, levels.t2)
                ),
            )
            if state.t1_touched_on is None:
                state = replace(state, t1_touched_on=day)
                events.append(Event(EventKind.T1_TOUCHED, day, levels.t1, levels.r(levels.t1)))
            events.append(Event(EventKind.T2_HIT, day, levels.t2, state.outcome_r))
            return state, events
        if bar.high >= levels.t1 and state.t1_touched_on is None:
            state = replace(state, t1_touched_on=day)
            events.append(Event(EventKind.T1_TOUCHED, day, levels.t1, levels.r(levels.t1)))
        state = replace(state, last_evaluated=day, last_close=bar.close)
    if today > expiry_day + UNVERIFIABLE_GRACE:
        state = replace(state, status=SignalStatus.UNVERIFIABLE, exit_day=today)
        events.append(Event(EventKind.UNVERIFIABLE, today, None, None))
    return state, events
