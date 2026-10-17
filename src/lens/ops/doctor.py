"""`lens doctor`: every check that decides whether tomorrow's briefing can arrive."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from lens.delivery.telegram import TelegramClient, TelegramError
from lens.settings import Secrets, Settings
from lens.storage.db import Database

Row = tuple[str, bool, str]


async def _database(secrets: Secrets, name: str, pooled: bool) -> Row:
    url = secrets.database_url_pooled if pooled else secrets.database_url_direct
    if url is None:
        if pooled:
            return (name, True, "not set here; the webhook reads it from Vercel")
        return (name, False, "DATABASE_URL_DIRECT is not set")
    try:
        db = Database(url.get_secret_value(), pooled=pooled, rollback_only=True)
    except Exception as error:  # a malformed URL is a failed check, not a crash
        return (name, False, type(error).__name__)
    try:
        await db.ping()
        return (name, True, "connected")
    except Exception as error:
        return (name, False, type(error).__name__)
    finally:
        await db.dispose()


async def run_doctor(settings: Settings, secrets: Secrets) -> list[Row]:
    from lens.pipeline.cycle import migration_head

    rows: list[Row] = [
        (
            "settings",
            True,
            f"{len(settings.watchlist)} assets, {len(settings.strategies)} strategies",
        )
    ]
    rows.append(await _database(secrets, "database (direct)", pooled=False))
    rows.append(await _database(secrets, "database (pooled)", pooled=True))
    if secrets.database_url_direct is not None:
        db = Database(secrets.database_url_direct.get_secret_value(), rollback_only=True)
        try:
            revision = await db.revision()
            head = migration_head()
            rows.append(("migrations", revision == head, f"database {revision}, code {head}"))
        except Exception as error:
            rows.append(("migrations", False, type(error).__name__))
        finally:
            await db.dispose()
    if secrets.telegram_bot_token is None:
        rows.append(("telegram", False, "TELEGRAM_BOT_TOKEN is not set"))
    else:
        client = TelegramClient(secrets.telegram_bot_token.get_secret_value())
        try:
            me = await client.get_me()
            info = await client.webhook_info()
            rows.append(("telegram bot", True, f"@{me.get('username')}"))
            last_error = info.get("last_error_date")
            recent = last_error and datetime.fromtimestamp(last_error, UTC) > datetime.now(
                UTC
            ) - timedelta(days=1)
            rows.append(
                (
                    "telegram webhook",
                    bool(info.get("url")) and not recent,
                    f"{info.get('url') or 'not set'}"
                    + (f" · last error {info.get('last_error_message')}" if recent else ""),
                )
            )
        except TelegramError as error:
            rows.append(("telegram bot", False, type(error).__name__))
        finally:
            await client.close()
    rows.append(
        (
            "owner",
            secrets.owner_telegram_id is not None,
            "OWNER_TELEGRAM_ID set"
            if secrets.owner_telegram_id
            else "OWNER_TELEGRAM_ID is not set",
        )
    )
    rows.append(
        (
            "healthchecks",
            secrets.healthcheck_ping_url is not None,
            "ping URL set" if secrets.healthcheck_ping_url else "HEALTHCHECK_PING_URL is not set",
        )
    )
    async with httpx.AsyncClient(timeout=10) as http:
        for name, url in (
            ("provider yahoo", "https://query1.finance.yahoo.com"),
            ("provider coinbase", "https://api.exchange.coinbase.com/time"),
            ("provider alpha vantage", "https://www.alphavantage.co"),
            ("fx bnm", "https://api.bnm.gov.my"),
        ):
            try:
                response = await http.get(url)
                rows.append((name, response.status_code < 500, f"HTTP {response.status_code}"))
            except httpx.HTTPError as error:
                rows.append((name, False, type(error).__name__))
    return rows
