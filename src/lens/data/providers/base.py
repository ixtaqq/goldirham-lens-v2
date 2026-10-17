from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Protocol, TypeVar

import httpx

from lens.domain.bars import Bar
from lens.domain.instruments import Instrument
from lens.domain.money import NonFiniteNumberError, to_decimal

T = TypeVar("T")
USER_AGENT = "goldirham-lens/2 (+private research briefing)"


class ProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, *, retryable: bool) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ProviderCall:
    provider: str
    ok: bool
    latency_ms: int
    error_class: str | None = None


@dataclass(slots=True)
class CallLog:
    calls: list[ProviderCall] = field(default_factory=list)

    def record(self, call: ProviderCall) -> None:
        self.calls.append(call)


@dataclass(frozen=True, slots=True)
class ProviderBars:
    provider: str
    bars: tuple[Bar, ...]
    splits: Mapping[date, Decimal] = field(default_factory=dict)


class BarProvider(Protocol):
    name: str

    async def fetch_daily(self, instrument: Instrument, start: date, end: date) -> ProviderBars: ...


def bar_from_values(symbol: str, day: date, provider: str, values: Mapping[str, Any]) -> Bar | None:
    """Parse provider numbers into a Bar; a value that is not a finite number drops the bar."""
    try:
        return Bar(
            symbol=symbol,
            day=day,
            open=to_decimal(values["open"]),
            high=to_decimal(values["high"]),
            low=to_decimal(values["low"]),
            close=to_decimal(values["close"]),
            volume=to_decimal(values.get("volume") or 0),
            provider=provider,
        )
    except (KeyError, NonFiniteNumberError):
        return None


async def with_retries[T](
    provider: str,
    action: Callable[[], Awaitable[T]],
    log: CallLog | None = None,
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
) -> T:
    """Run `action`, retrying retryable failures with jittered exponential backoff."""
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            result = await action()
        except ProviderError as error:
            _log(log, provider, started, type(error).__name__, ok=False)
            if not error.retryable or attempt == attempts:
                raise
        except (httpx.TimeoutException, httpx.TransportError) as error:
            _log(log, provider, started, type(error).__name__, ok=False)
            if attempt == attempts:
                raise ProviderError(provider, type(error).__name__, retryable=True) from error
        else:
            _log(log, provider, started, None, ok=True)
            return result
        await asyncio.sleep(base_delay * 2 ** (attempt - 1) * (0.5 + random.random()))  # noqa: S311 - retry jitter
    raise AssertionError("unreachable")


def _log(
    log: CallLog | None, provider: str, started: float, error: str | None, *, ok: bool
) -> None:
    if log is not None:
        log.record(ProviderCall(provider, ok, int((time.monotonic() - started) * 1000), error))


def raise_for_status(provider: str, response: httpx.Response) -> None:
    if response.status_code == 429 or response.status_code >= 500:
        raise ProviderError(provider, f"HTTP {response.status_code}", retryable=True)
    if response.status_code >= 400:
        raise ProviderError(provider, f"HTTP {response.status_code}", retryable=False)


def http_client(timeout: float = 20.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=10.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )
