"""Healthchecks.io pings. A failed ping is logged and never fails the job it reports on."""

from __future__ import annotations

import httpx

from lens.logs import get_logger

log = get_logger("lens.ops.health")


async def ping(url: str | None, suffix: str = "", *, body: str = "") -> bool:
    if not url:
        return False
    target = url.rstrip("/") + (f"/{suffix}" if suffix else "")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(target, content=body[:10_000].encode())
        return response.status_code < 400
    except httpx.HTTPError as error:
        log.warning(
            "healthcheck ping failed", error=type(error).__name__, suffix=suffix or "success"
        )
        return False
