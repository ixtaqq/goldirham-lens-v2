"""Indicators are checked against independent pandas implementations of the same formulas."""

from __future__ import annotations

import math
import random
from datetime import date

import pandas as pd
import pytest

from lens.domain.indicators import (
    atr,
    bollinger,
    compute_indicators,
    ema_series,
    last_swing_low,
    macd,
    prior_high,
    rsi,
    sma,
)
from lens.domain.market_view import MarketView
from tests.helpers import make_bars


def _random_walk(n: int = 300, seed: int = 3) -> tuple[list[float], list[float], list[float]]:
    rng = random.Random(seed)
    closes, highs, lows = [], [], []
    price = 100.0
    for _ in range(n):
        price *= math.exp(rng.gauss(0, 0.015))
        high = price * (1 + abs(rng.gauss(0, 0.01)))
        low = price * (1 - abs(rng.gauss(0, 0.01)))
        closes.append(price)
        highs.append(high)
        lows.append(low)
    return closes, highs, lows


def _pandas_wilder(series: pd.Series, period: int) -> pd.Series:
    seed = series.iloc[:period].mean()
    values = [math.nan] * (period - 1) + [seed]
    for value in series.iloc[period:]:
        values.append((values[-1] * (period - 1) + value) / period)
    return pd.Series(values, index=series.index)


def test_rsi_matches_an_independent_wilder_implementation() -> None:
    closes, _, _ = _random_walk()
    delta = pd.Series(closes).diff().dropna().reset_index(drop=True)
    gains = _pandas_wilder(delta.clip(lower=0), 14)
    losses = _pandas_wilder(-delta.clip(upper=0), 14)
    expected = 100 - 100 / (1 + gains.iloc[-1] / losses.iloc[-1])
    assert rsi(closes, 14) == pytest.approx(expected, abs=1e-9)


def test_atr_matches_an_independent_wilder_implementation() -> None:
    closes, highs, lows = _random_walk()
    frame = pd.DataFrame({"h": highs, "l": lows, "c": closes})
    previous = frame["c"].shift(1)
    tr = pd.concat(
        [frame["h"] - frame["l"], (frame["h"] - previous).abs(), (frame["l"] - previous).abs()],
        axis=1,
    ).max(axis=1)
    expected = _pandas_wilder(tr.iloc[1:].reset_index(drop=True), 14).iloc[-1]
    assert atr(highs, lows, closes, 14) == pytest.approx(expected, abs=1e-9)


def test_sma_ema_macd_and_bands_match_pandas() -> None:
    closes, _, _ = _random_walk()
    series = pd.Series(closes)
    assert sma(closes, 50) == pytest.approx(series.rolling(50).mean().iloc[-1], abs=1e-9)

    def ema(values: pd.Series, n: int) -> pd.Series:
        seeded = values.copy()
        seeded.iloc[: n - 1] = math.nan
        seeded.iloc[n - 1] = values.iloc[:n].mean()
        return seeded.ewm(span=n, adjust=False, ignore_na=True).mean()

    assert ema_series(closes, 26)[-1] == pytest.approx(ema(series, 26).iloc[-1], abs=1e-9)
    line = ema(series, 12) - ema(series, 26)
    signal = ema(line.dropna().reset_index(drop=True), 9).iloc[-1]
    result = macd(closes)
    assert result is not None
    assert result.line == pytest.approx(line.iloc[-1], abs=1e-9)
    assert result.signal == pytest.approx(signal, abs=1e-9)
    bands = bollinger(closes, 20, 2)
    assert bands is not None
    assert bands.upper == pytest.approx(
        series.rolling(20).mean().iloc[-1] + 2 * series.rolling(20).std(ddof=0).iloc[-1], abs=1e-9
    )


def test_rsi_of_a_steady_rise_is_100_and_short_history_is_none() -> None:
    assert rsi([float(i) for i in range(1, 30)], 14) == 100.0
    assert rsi([1.0] * 14, 14) is None


def test_swing_low_only_counts_confirmed_fractals() -> None:
    lows = [10, 9, 8, 9, 10, 11, 12, 7, 8]
    # index 7 (7.0) is not confirmed: only one bar follows it
    assert last_swing_low([float(x) for x in lows], radius=2) == 8.0


def test_prior_high_excludes_the_latest_session() -> None:
    assert prior_high([1.0, 5.0, 3.0, 9.0], lookback=3) == 5.0


def test_compute_indicators_reports_sessions_used() -> None:
    view = MarketView.of("X", make_bars("X", [100 + i for i in range(250)]), as_of=date(2030, 1, 1))
    result = compute_indicators(view)
    assert result.sessions_used == 250
    assert result.sma200 is not None
    assert result.close == 349.0
