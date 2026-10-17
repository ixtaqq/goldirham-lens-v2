"""Alpha Vantage TIME_SERIES_DAILY (free tier, unadjusted), used as the US cross-check."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from lens.data.providers.base import (
    CallLog,
    ProviderBars,
    ProviderError,
    bar_from_values,
    http_client,
    raise_for_status,
    with_retries,
)
from lens.domain.instruments import Instrument

URL = "https://www.alphavantage.co/query"
NAME = "alphavantage"


class AlphaVantageProvider:
    name = NAME

    def __init__(
        self,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        log: CallLog | None = None,
    ) -> None:
        self._key = api_key
        self._client = client
        self._log = log

    async def fetch_daily(self, instrument: Instrument, start: date, end: date) -> ProviderBars:
        if not self._key:
            raise ProviderError(NAME, "ALPHA_VANTAGE_API_KEY is not set", retryable=False)
        key = self._key
        client = self._client or http_client()

        async def call() -> Any:
            response = await client.get(
                URL,
                params={
                    "function": "TIME_SERIES_DAILY",
                    "symbol": instrument.symbol,
                    "outputsize": "compact",
                    "apikey": key,
                },
            )
            raise_for_status(NAME, response)
            return response.json()

        try:
            payload = await with_retries(NAME, call, self._log, attempts=2)
        finally:
            if self._client is None:
                await client.aclose()
        return parse_alphavantage(instrument.symbol, payload, start, end)


def parse_alphavantage(symbol: str, payload: Any, start: date, end: date) -> ProviderBars:
    if not isinstance(payload, dict):
        raise ProviderError(NAME, "unexpected payload", retryable=False)
    for key in ("Note", "Information", "Error Message"):
        if key in payload:
            raise ProviderError(NAME, f"{key.lower()}: request refused", retryable=False)
    series = payload.get("Time Series (Daily)")
    if not isinstance(series, dict):
        raise ProviderError(NAME, f"no series for {symbol}", retryable=False)
    bars = []
    for raw_day, values in series.items():
        try:
            day = date.fromisoformat(raw_day)
        except ValueError:
            continue
        if not (start <= day <= end) or not isinstance(values, dict):
            continue
        parsed = bar_from_values(
            symbol,
            day,
            NAME,
            {
                "open": values.get("1. open"),
                "high": values.get("2. high"),
                "low": values.get("3. low"),
                "close": values.get("4. close"),
                "volume": values.get("5. volume") or "0",
            },
        )
        if parsed is not None:
            bars.append(parsed)
    if not bars:
        raise ProviderError(NAME, f"no rows for {symbol} in range", retryable=False)
    return ProviderBars(NAME, tuple(sorted(bars, key=lambda b: b.day)))
