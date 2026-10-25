from __future__ import annotations

from datetime import date
from decimal import Decimal

from lens.domain.alerts import Direction, LevelAlert, first_crossing
from lens.domain.bars import BarQuality
from tests.helpers import make_bars

DAYS = [date(2026, 10, d) for d in (12, 13, 14, 15, 16)]
BARS = make_bars("AAPL", [190, 198, 203, 207, 196], days=DAYS)


def _alert(direction: Direction, level: str, created_on: date = date(2026, 10, 12)) -> LevelAlert:
    return LevelAlert(1, "AAPL", direction, Decimal(level), created_on)


def test_the_first_close_beyond_the_level_after_the_alert_day_fires() -> None:
    hit = first_crossing(_alert(Direction.ABOVE, "200"), BARS)
    assert hit is not None
    assert (hit.day, hit.close) == (date(2026, 10, 14), Decimal(203))

    below = first_crossing(_alert(Direction.BELOW, "197", created_on=date(2026, 10, 13)), BARS)
    assert below is not None
    assert (below.day, below.close) == (date(2026, 10, 16), Decimal(196))


def test_a_close_exactly_at_the_level_counts() -> None:
    hit = first_crossing(_alert(Direction.ABOVE, "203"), BARS)
    assert hit is not None
    assert hit.day == date(2026, 10, 14)


def test_closes_on_or_before_the_alert_day_and_unverified_closes_never_fire() -> None:
    assert (
        first_crossing(_alert(Direction.BELOW, "195", created_on=date(2026, 10, 12)), BARS) is None
    )
    assert (
        first_crossing(_alert(Direction.ABOVE, "189", created_on=date(2026, 10, 16)), BARS) is None
    )
    suspect = [
        b if b.day != date(2026, 10, 14) else b.with_quality(BarQuality.SUSPECT) for b in BARS
    ]
    hit = first_crossing(_alert(Direction.ABOVE, "200"), suspect)
    assert hit is not None
    assert hit.day == date(2026, 10, 15)
