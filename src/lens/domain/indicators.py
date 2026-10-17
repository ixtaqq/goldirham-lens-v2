"""Technical indicators as pure functions over float sequences.

Floats are fine here: indicators are inputs to rules, never displayed prices. Each function
returns the latest value, or None when there is not enough history.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from lens.domain.market_view import MarketView


def sma_series(values: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    window = sum(values[:period])
    out[period - 1] = window / period
    for i in range(period, len(values)):
        window += values[i] - values[i - period]
        out[i] = window / period
    return out


def sma(values: Sequence[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    alpha = 2.0 / (period + 1)
    current = sum(values[:period]) / period
    out[period - 1] = current
    for i in range(period, len(values)):
        current = alpha * values[i] + (1 - alpha) * current
        out[i] = current
    return out


def _wilder(values: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    current = sum(values[:period]) / period
    out[period - 1] = current
    for i in range(period, len(values)):
        current = (current * (period - 1) + values[i]) / period
        out[i] = current
    return out


def rsi(closes: Sequence[float], period: int = 14) -> float | None:
    """Wilder's RSI. Needs period + 1 closes."""
    if len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = _wilder([max(c, 0.0) for c in changes], period)[-1]
    losses = _wilder([max(-c, 0.0) for c in changes], period)[-1]
    assert gains is not None
    assert losses is not None
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gains / losses)


def true_ranges(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> list[float]:
    ranges = []
    for i in range(1, len(closes)):
        previous = closes[i - 1]
        ranges.append(max(highs[i] - lows[i], abs(highs[i] - previous), abs(lows[i] - previous)))
    return ranges


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> float | None:
    """Wilder's average true range. Needs period + 1 bars."""
    if len(closes) < period + 1:
        return None
    return _wilder(true_ranges(highs, lows, closes), period)[-1]


@dataclass(frozen=True, slots=True)
class Macd:
    line: float
    signal: float
    histogram: float


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Macd | None:
    fast_ema = ema_series(closes, fast)
    slow_ema = ema_series(closes, slow)
    line = [
        f - s for f, s in zip(fast_ema, slow_ema, strict=True) if f is not None and s is not None
    ]
    signal_series = ema_series(line, signal)
    if not line or signal_series[-1] is None:
        return None
    last_signal = signal_series[-1]
    return Macd(line[-1], last_signal, line[-1] - last_signal)


@dataclass(frozen=True, slots=True)
class Bands:
    upper: float
    middle: float
    lower: float


def bollinger(closes: Sequence[float], period: int = 20, width: float = 2.0) -> Bands | None:
    if len(closes) < period:
        return None
    window = closes[-period:]
    middle = sum(window) / period
    deviation = math.sqrt(sum((value - middle) ** 2 for value in window) / period)
    return Bands(middle + width * deviation, middle, middle - width * deviation)


def last_swing_low(lows: Sequence[float], radius: int = 2) -> float | None:
    """Most recent confirmed fractal low: lowest within `radius` bars on both sides."""
    for i in range(len(lows) - 1 - radius, radius - 1, -1):
        window = lows[i - radius : i + radius + 1]
        if lows[i] == min(window):
            return lows[i]
    return None


def last_swing_high(highs: Sequence[float], radius: int = 2) -> float | None:
    for i in range(len(highs) - 1 - radius, radius - 1, -1):
        window = highs[i - radius : i + radius + 1]
        if highs[i] == max(window):
            return highs[i]
    return None


def prior_high(highs: Sequence[float], lookback: int) -> float | None:
    """Highest high over the `lookback` sessions before the latest one."""
    if len(highs) < lookback + 1:
        return None
    return max(highs[-lookback - 1 : -1])


def realized_volatility(
    closes: Sequence[float], period: int = 20, periods_per_year: int = 252
) -> float | None:
    if len(closes) < period + 1 or any(value <= 0 for value in closes[-period - 1 :]):
        return None
    returns = [
        math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - period, len(closes))
    ]
    mean = sum(returns) / period
    variance = sum((r - mean) ** 2 for r in returns) / (period - 1)
    return math.sqrt(variance) * math.sqrt(periods_per_year) * 100


def trailing_return(closes: Sequence[float], period: int) -> float | None:
    if len(closes) < period + 1 or closes[-period - 1] <= 0:
        return None
    return (closes[-1] / closes[-period - 1] - 1) * 100


@dataclass(frozen=True, slots=True)
class IndicatorSet:
    sessions_used: int
    close: float
    sma20: float | None
    sma50: float | None
    sma200: float | None
    rsi14: float | None
    atr14: float | None
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None
    bb_upper: float | None
    bb_lower: float | None
    high_52w: float | None
    low_52w: float | None
    swing_low: float | None
    swing_high: float | None
    realized_vol_20: float | None
    volume_avg_50: float | None
    return_63: float | None

    def as_dict(self) -> dict[str, float | int | None]:
        return asdict(self)


def compute_indicators(
    view: MarketView, *, periods_per_year: int = 252, lookback_52w: int = 252
) -> IndicatorSet:
    closes, highs, lows, volumes = view.closes(), view.highs(), view.lows(), view.volumes()
    if not closes:
        raise ValueError(f"no bars for {view.symbol}")
    macd_value = macd(closes)
    bands = bollinger(closes)
    window_highs = highs[-lookback_52w:]
    window_lows = lows[-lookback_52w:]
    return IndicatorSet(
        sessions_used=len(closes),
        close=closes[-1],
        sma20=sma(closes, 20),
        sma50=sma(closes, 50),
        sma200=sma(closes, 200),
        rsi14=rsi(closes, 14),
        atr14=atr(highs, lows, closes, 14),
        macd=macd_value.line if macd_value else None,
        macd_signal=macd_value.signal if macd_value else None,
        macd_histogram=macd_value.histogram if macd_value else None,
        bb_upper=bands.upper if bands else None,
        bb_lower=bands.lower if bands else None,
        high_52w=max(window_highs) if len(highs) >= lookback_52w else None,
        low_52w=min(window_lows) if len(lows) >= lookback_52w else None,
        swing_low=last_swing_low(lows),
        swing_high=last_swing_high(highs),
        realized_vol_20=realized_volatility(closes, 20, periods_per_year),
        volume_avg_50=sma(volumes, 50),
        return_63=trailing_return(closes, 63),
    )
