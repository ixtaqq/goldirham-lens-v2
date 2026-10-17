"""Context only: crypto Fear & Greed and business headlines. Never a trigger for anything."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import feedparser
import httpx

from lens.data.providers.base import (
    CallLog,
    ProviderError,
    http_client,
    raise_for_status,
    with_retries,
)
from lens.domain.briefing import Headline


@dataclass(frozen=True, slots=True)
class FearGreed:
    value: int
    label: str


def parse_fear_greed(payload: Any) -> FearGreed:
    try:
        item = payload["data"][0]
        value = int(item["value"])
        if not 0 <= value <= 100:
            raise ValueError(value)
        return FearGreed(value, str(item["value_classification"]))
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ProviderError("alternative.me", "unexpected payload", retryable=False) from error


async def fetch_fear_greed(
    url: str, client: httpx.AsyncClient | None = None, log: CallLog | None = None
) -> FearGreed:
    http = client or http_client()

    async def call() -> FearGreed:
        response = await http.get(url, params={"limit": 1, "format": "json"})
        raise_for_status("alternative.me", response)
        return parse_fear_greed(response.json())

    try:
        return await with_retries("alternative.me", call, log, attempts=2)
    finally:
        if client is None:
            await http.aclose()


def parse_feed(content: bytes, limit: int) -> list[Headline]:
    parsed = feedparser.parse(content)
    source = str(parsed.feed.get("title") or "feed").strip()[:60]
    headlines = []
    for entry in parsed.entries[:limit]:
        title = " ".join(str(entry.get("title", "")).split())
        if title:
            headlines.append(Headline(title=title[:200], source=source))
    return headlines


async def fetch_headlines(
    feeds: tuple[str, ...],
    limit: int,
    client: httpx.AsyncClient | None = None,
    log: CallLog | None = None,
) -> list[Headline]:
    http = client or http_client(timeout=10)
    collected: list[Headline] = []
    try:
        for url in feeds:

            async def call(target: str = url) -> bytes:
                response = await http.get(target)
                raise_for_status("rss", response)
                return response.content

            try:
                collected.extend(
                    parse_feed(await with_retries("rss", call, log, attempts=2), limit)
                )
            except ProviderError:
                continue
    finally:
        if client is None:
            await http.aclose()
    seen: set[str] = set()
    unique = []
    for headline in collected:
        if headline.title.lower() not in seen:
            seen.add(headline.title.lower())
            unique.append(headline)
    return unique[:limit]
