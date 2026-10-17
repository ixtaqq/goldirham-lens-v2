from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from lens.domain.instruments import Market


@dataclass(frozen=True, slots=True)
class Session:
    market: Market
    day: date
    open_utc: datetime
    close_utc: datetime

    def is_closed(self, now: datetime) -> bool:
        return self.close_utc <= now


class SessionCalendar(Protocol):
    """Exchange sessions. Implementations live in lens.data.calendars."""

    market: Market

    def session(self, day: date) -> Session | None: ...

    def sessions_between(self, start: date, end: date) -> list[Session]:
        """Sessions whose day falls in [start, end], oldest first."""
        ...

    def closed_sessions(self, now: datetime, count: int) -> list[Session]:
        """The most recent `count` sessions that closed at or before `now`, oldest first."""
        ...
