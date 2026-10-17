"""Yahoo Finance via yfinance (an unofficial API). Closes are split-adjusted, not dividend-adjusted."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import yfinance as yf

from lens.data.providers.base import (
    CallLog,
    ProviderBars,
    ProviderError,
    bar_from_values,
    with_retries,
)
from lens.domain.instruments import Instrument
from lens.domain.money import NonFiniteNumberError, to_decimal

NAME = "yahoo"
TIMEOUT_SECONDS = 45
# Surface provider failures as exceptions instead of empty frames, so retries and fallbacks run.
yf.config.debug.hide_exceptions = False


def _history(symbol: str, start: date, end: date) -> Any:
    ticker = yf.Ticker(symbol)
    return ticker.history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        actions=True,
        timeout=20,
    )


class YahooProvider:
    name = NAME

    def __init__(self, log: CallLog | None = None) -> None:
        self._log = log

    async def fetch_daily(self, instrument: Instrument, start: date, end: date) -> ProviderBars:
        async def call() -> Any:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(_history, instrument.symbol, start, end), TIMEOUT_SECONDS
                )
            except TimeoutError as error:
                raise ProviderError(NAME, "timeout", retryable=True) from error
            except Exception as error:  # yfinance raises many unrelated types
                raise ProviderError(NAME, type(error).__name__, retryable=True) from error

        frame = await with_retries(NAME, call, self._log)
        return parse_history(instrument.symbol, frame)


def parse_history(symbol: str, frame: Any) -> ProviderBars:
    bars = []
    splits: dict[date, Decimal] = {}
    if frame is None or len(frame) == 0:
        raise ProviderError(NAME, f"no rows for {symbol}", retryable=False)
    for index, row in frame.sort_index().iterrows():
        day = index.date()
        parsed = bar_from_values(
            symbol,
            day,
            NAME,
            {
                "open": row.get("Open"),
                "high": row.get("High"),
                "low": row.get("Low"),
                "close": row.get("Close"),
                "volume": row.get("Volume"),
            },
        )
        if parsed is not None:
            bars.append(parsed)
        ratio = row.get("Stock Splits")
        try:
            value = to_decimal(float(ratio)) if ratio is not None else Decimal(0)
        except (NonFiniteNumberError, TypeError, ValueError):
            value = Decimal(0)
        if value > 0:
            splits[day] = value
    return ProviderBars(NAME, tuple(bars), splits)


def fetch_fundamentals_sync(symbol: str) -> dict[str, Any]:
    info: dict[str, Any] = yf.Ticker(symbol).info or {}
    return {"pe_ratio": info.get("trailingPE"), "revenue_growth": info.get("revenueGrowth")}
