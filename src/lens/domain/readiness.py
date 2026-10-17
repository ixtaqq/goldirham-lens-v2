from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from lens.domain.bars import QUALITY_REASON, Bar, BarQuality
from lens.domain.reasons import ReasonCode


@dataclass(frozen=True, slots=True)
class Readiness:
    """Whether an asset's history can feed a setup, and if not, why."""

    reasons: tuple[ReasonCode, ...]
    latest_session: date | None
    verified_sessions: int
    required_sessions: int

    @property
    def ready(self) -> bool:
        return not self.reasons


def assess_readiness(
    bars: Sequence[Bar],
    expected_sessions: Sequence[date],
    *,
    single_source_allowed: bool,
    recent_sessions: int = 5,
) -> Readiness:
    """Check the last `len(expected_sessions)` closed sessions are present and usable.

    `expected_sessions` comes from the exchange calendar, oldest first. Holidays are simply
    absent from it, so they are never counted as missing.
    """
    required = len(expected_sessions)
    by_day = {bar.day: bar for bar in bars}
    latest = max(by_day) if by_day else None
    if not by_day:
        return Readiness((ReasonCode.NO_COMPLETED_HISTORY,), None, 0, required)
    reasons: list[ReasonCode] = []
    if expected_sessions and latest != expected_sessions[-1]:
        reasons.append(ReasonCode.STALE_SESSION)
    present = [day for day in expected_sessions if day in by_day]
    if len(present) < required:
        if len(by_day) < required:
            reasons.append(ReasonCode.INSUFFICIENT_HISTORY)
        else:
            reasons.append(ReasonCode.MISSING_SESSION)
    recent = set(expected_sessions[-recent_sessions:])
    usable = 0
    for day in present:
        bar = by_day[day]
        if bar.quality is BarQuality.VERIFIED:
            usable += 1
            continue
        if bar.quality is BarQuality.SINGLE_SOURCE and (single_source_allowed or day not in recent):
            usable += 1
            continue
        reasons.append(QUALITY_REASON[bar.quality])
    return Readiness(tuple(dict.fromkeys(reasons)), latest, usable, required)
