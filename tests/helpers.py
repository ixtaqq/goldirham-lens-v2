from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from lens.domain.bars import Bar, BarQuality


def business_days(start: date, count: int) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def make_bars(
    symbol: str,
    closes: Sequence[float | str | Decimal],
    *,
    start: date = date(2025, 1, 2),
    spread: str = "0.01",
    volume: int = 1_000_000,
    days: Sequence[date] | None = None,
    quality: BarQuality = BarQuality.VERIFIED,
) -> list[Bar]:
    """Daily bars where open is the previous close and high/low straddle the body by `spread`."""
    session_days = list(days) if days is not None else business_days(start, len(closes))
    width = Decimal(spread)
    bars: list[Bar] = []
    previous: Decimal | None = None
    for day, raw in zip(session_days, closes, strict=True):
        close = Decimal(str(raw))
        open_ = previous if previous is not None else close
        high = max(open_, close) * (1 + width)
        low = min(open_, close) * (1 - width)
        bars.append(Bar(symbol, day, open_, high, low, close, Decimal(volume), "test", quality))
        previous = close
    return bars


def bar(symbol: str, day: date, o: str, h: str, low: str, c: str, v: str = "1000") -> Bar:
    return Bar(symbol, day, Decimal(o), Decimal(h), Decimal(low), Decimal(c), Decimal(v), "test")


def uptrend_then_pullback(length: int = 260, pullback: int = 6) -> list[float]:
    """A steady uptrend followed by a short, sharp pullback."""
    closes = [100.0 * (1.003**i) for i in range(length - pullback)]
    peak = closes[-1]
    closes += [peak * (1 - 0.018 * (i + 1)) for i in range(pullback)]
    return closes
