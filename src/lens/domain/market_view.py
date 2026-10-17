from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date

from lens.domain.bars import Bar


class LookAheadError(RuntimeError):
    """Raised when code asks for a bar after the view's as-of session."""


@dataclass(frozen=True, slots=True)
class MarketView:
    """Read-only bars for one symbol, up to and including `as_of`. Nothing later is reachable."""

    symbol: str
    as_of: date
    _bars: tuple[Bar, ...]

    @classmethod
    def of(cls, symbol: str, bars: Iterable[Bar], as_of: date) -> MarketView:
        by_day: dict[date, Bar] = {}
        for bar in bars:
            if bar.symbol != symbol:
                raise ValueError(f"bar for {bar.symbol} in view of {symbol}")
            if bar.day <= as_of:
                by_day[bar.day] = bar
        return cls(symbol, as_of, tuple(by_day[day] for day in sorted(by_day)))

    def __len__(self) -> int:
        return len(self._bars)

    def __iter__(self) -> Iterator[Bar]:
        return iter(self._bars)

    @property
    def bars(self) -> tuple[Bar, ...]:
        return self._bars

    def last(self) -> Bar:
        if not self._bars:
            raise LookupError(f"no bars for {self.symbol} up to {self.as_of}")
        return self._bars[-1]

    def bar_on(self, day: date) -> Bar | None:
        if day > self.as_of:
            raise LookAheadError(f"{self.symbol}: {day} is after as-of {self.as_of}")
        for bar in reversed(self._bars):
            if bar.day == day:
                return bar
            if bar.day < day:
                return None
        return None

    def since(self, day: date) -> MarketView:
        return MarketView(self.symbol, self.as_of, tuple(b for b in self._bars if b.day >= day))

    def closes(self) -> list[float]:
        return [float(bar.close) for bar in self._bars]

    def highs(self) -> list[float]:
        return [float(bar.high) for bar in self._bars]

    def lows(self) -> list[float]:
        return [float(bar.low) for bar in self._bars]

    def volumes(self) -> list[float]:
        return [float(bar.volume) for bar in self._bars]

    def days(self) -> list[date]:
        return [bar.day for bar in self._bars]
