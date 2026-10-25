"""Close-based level alerts. Only a verified completed close can fire one, and only once."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from lens.domain.bars import Bar


class Direction(StrEnum):
    ABOVE = "above"
    BELOW = "below"


@dataclass(frozen=True, slots=True)
class LevelAlert:
    id: int
    symbol: str
    direction: Direction
    level: Decimal
    created_on: date


@dataclass(frozen=True, slots=True)
class AlertHit:
    alert: LevelAlert
    day: date
    close: Decimal


def first_crossing(alert: LevelAlert, bars: Sequence[Bar]) -> AlertHit | None:
    """The first usable close after the day the alert was set that reaches the level."""
    for bar in sorted(bars, key=lambda b: b.day):
        if bar.day <= alert.created_on or not bar.usable:
            continue
        reached = (
            bar.close >= alert.level
            if alert.direction is Direction.ABOVE
            else bar.close <= alert.level
        )
        if reached:
            return AlertHit(alert, bar.day, bar.close)
    return None
