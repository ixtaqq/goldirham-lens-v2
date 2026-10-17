"""Exchange calendars. XNYS and XKLS come from exchange_calendars; crypto uses UTC days."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from functools import cache

import exchange_calendars as xcals
import pandas as pd

from lens.domain.instruments import Market
from lens.domain.sessions import Session, SessionCalendar

_EXCHANGE_CODES = {Market.XNYS: "XNYS", Market.XKLS: "XKLS"}
_FIRST_YEAR = 2015


class ExchangeCalendar:
    def __init__(self, market: Market, extra_holidays: frozenset[date] = frozenset()) -> None:
        self.market = market
        end = date.today() + timedelta(days=400)  # noqa: DTZ011 - calendar bound only
        calendar = xcals.get_calendar(
            _EXCHANGE_CODES[market], start=f"{_FIRST_YEAR}-01-01", end=end.isoformat()
        )
        schedule = calendar.schedule
        self._days: list[date] = [
            ts.date() for ts in schedule.index if ts.date() not in extra_holidays
        ]
        self._sessions: dict[date, Session] = {
            ts.date(): Session(market, ts.date(), _utc(row["open"]), _utc(row["close"]))
            for ts, row in schedule.iterrows()
            if ts.date() not in extra_holidays
        }

    def session(self, day: date) -> Session | None:
        return self._sessions.get(day)

    def sessions_between(self, start: date, end: date) -> list[Session]:
        return [self._sessions[d] for d in self._days if start <= d <= end]

    def closed_sessions(self, now: datetime, count: int) -> list[Session]:
        today = now.astimezone(UTC).date() + timedelta(days=1)
        closed = [
            self._sessions[d] for d in self._days if d <= today and self._sessions[d].is_closed(now)
        ]
        return closed[-count:] if count else []


class CryptoCalendar:
    """Every UTC day is a session from 00:00 to 24:00 UTC."""

    market = Market.CRYPTO_UTC

    def session(self, day: date) -> Session:
        start = datetime.combine(day, time.min, UTC)
        return Session(self.market, day, start, start + timedelta(days=1))

    def sessions_between(self, start: date, end: date) -> list[Session]:
        return [self.session(start + timedelta(days=i)) for i in range((end - start).days + 1)]

    def closed_sessions(self, now: datetime, count: int) -> list[Session]:
        last_closed = now.astimezone(UTC).date() - timedelta(days=1)
        first = last_closed - timedelta(days=count - 1)
        return self.sessions_between(first, last_closed) if count else []


def _utc(value: pd.Timestamp) -> datetime:
    stamp = value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")
    result: datetime = stamp.to_pydatetime()
    return result


@cache
def calendar_for(market: Market, extra_holidays: frozenset[date] = frozenset()) -> SessionCalendar:
    if market is Market.CRYPTO_UTC:
        return CryptoCalendar()
    return ExchangeCalendar(market, extra_holidays)
