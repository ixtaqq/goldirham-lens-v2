"""Crypto daily candles from exchange public market-data APIs (UTC day sessions)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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

COINBASE_URL = "https://api.exchange.coinbase.com/products/{product}/candles"
COINBASE_MAX_CANDLES = 300
BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"


class CoinbaseProvider:
    """Coinbase Exchange candles: [time, low, high, open, close, volume], newest first."""

    name = "coinbase"

    def __init__(self, client: httpx.AsyncClient | None = None, log: CallLog | None = None) -> None:
        self._client = client
        self._log = log

    async def fetch_daily(self, instrument: Instrument, start: date, end: date) -> ProviderBars:
        client = self._client or http_client()
        try:
            rows: list[list[Any]] = []
            window_start = start
            while window_start <= end:
                window_end = min(end, window_start + timedelta(days=COINBASE_MAX_CANDLES - 1))
                rows.extend(await self._window(client, instrument.symbol, window_start, window_end))
                window_start = window_end + timedelta(days=1)
        finally:
            if self._client is None:
                await client.aclose()
        return parse_coinbase(instrument.symbol, rows)

    async def _window(
        self, client: httpx.AsyncClient, product: str, start: date, end: date
    ) -> list[list[Any]]:
        async def call() -> list[list[Any]]:
            response = await client.get(
                COINBASE_URL.format(product=product),
                params={
                    "granularity": 86400,
                    "start": f"{start.isoformat()}T00:00:00Z",
                    "end": f"{end.isoformat()}T23:59:59Z",
                },
            )
            raise_for_status(self.name, response)
            payload = response.json()
            if not isinstance(payload, list):
                raise ProviderError(self.name, "unexpected payload", retryable=False)
            return payload

        return await with_retries(self.name, call, self._log)


def parse_coinbase(symbol: str, rows: list[list[Any]]) -> ProviderBars:
    bars = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        day = datetime.fromtimestamp(int(row[0]), UTC).date()
        parsed = bar_from_values(
            symbol,
            day,
            "coinbase",
            {"low": row[1], "high": row[2], "open": row[3], "close": row[4], "volume": row[5]},
        )
        if parsed is not None:
            bars[day] = parsed
    if not bars:
        raise ProviderError("coinbase", f"no candles for {symbol}", retryable=False)
    return ProviderBars("coinbase", tuple(bars[d] for d in sorted(bars)))


class BinanceProvider:
    """Binance public market data (`data-api.binance.vision`). USD pairs map to USDT."""

    name = "binance"

    def __init__(self, client: httpx.AsyncClient | None = None, log: CallLog | None = None) -> None:
        self._client = client
        self._log = log

    async def fetch_daily(self, instrument: Instrument, start: date, end: date) -> ProviderBars:
        base = instrument.symbol.removesuffix("-USD")
        client = self._client or http_client()

        async def call() -> list[list[Any]]:
            response = await client.get(
                BINANCE_URL,
                params={
                    "symbol": f"{base}USDT",
                    "interval": "1d",
                    "startTime": int(
                        datetime.combine(start, datetime.min.time(), UTC).timestamp() * 1000
                    ),
                    "endTime": int(
                        datetime.combine(end, datetime.max.time(), UTC).timestamp() * 1000
                    ),
                    "limit": 1000,
                },
            )
            raise_for_status(self.name, response)
            payload = response.json()
            if not isinstance(payload, list):
                raise ProviderError(self.name, "unexpected payload", retryable=False)
            return payload

        try:
            rows = await with_retries(self.name, call, self._log)
        finally:
            if self._client is None:
                await client.aclose()
        return parse_binance(instrument.symbol, rows)


def parse_binance(symbol: str, rows: list[list[Any]]) -> ProviderBars:
    bars = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        day = datetime.fromtimestamp(int(row[0]) / 1000, UTC).date()
        parsed = bar_from_values(
            symbol,
            day,
            "binance",
            {"open": row[1], "high": row[2], "low": row[3], "close": row[4], "volume": row[5]},
        )
        if parsed is not None:
            bars.append(parsed)
    if not bars:
        raise ProviderError("binance", f"no klines for {symbol}", retryable=False)
    return ProviderBars("binance", tuple(sorted(bars, key=lambda b: b.day)))
