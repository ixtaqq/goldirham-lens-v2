"""Telegram webhook (FastAPI). Rejects any request without the secret token before reading it."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request, Response
from pydantic import ValidationError

import lens.bot.commands  # noqa: F401 - registers commands
from lens.bot.router import BotContext, handle_update
from lens.bot.updates import Update
from lens.delivery.telegram import TelegramClient
from lens.logs import configure_logging, get_logger
from lens.settings import Secrets, Settings, load_settings
from lens.storage.db import Database

log = get_logger("lens.webhook")
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
TELEGRAM_TIMEOUT_SECONDS = 8.0


class GitHubDispatcher:
    def __init__(self, token: str, repository: str) -> None:
        self._token = token
        self._repository = repository

    async def dispatch(self, workflow: str, inputs: dict[str, str]) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"https://api.github.com/repos/{self._repository}/actions/workflows/{workflow}/dispatches",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={"ref": "main", "inputs": inputs},
            )
            response.raise_for_status()


@dataclass(slots=True)
class _Runtime:
    settings: Settings
    secrets: Secrets
    db: Database
    telegram: TelegramClient
    dispatcher: GitHubDispatcher | None


_runtime: _Runtime | None = None


def runtime() -> _Runtime:
    """Created once per warm function instance."""
    global _runtime
    if _runtime is None:
        secrets = Secrets()
        configure_logging(secrets.secret_values())
        url = secrets.database_url_pooled or secrets.database_url_direct
        if url is None:
            raise RuntimeError("DATABASE_URL_POOLED is not set")
        dispatcher = None
        if secrets.github_dispatch_token and secrets.github_repository:
            dispatcher = GitHubDispatcher(
                secrets.github_dispatch_token.get_secret_value(), secrets.github_repository
            )
        _runtime = _Runtime(
            load_settings(),
            secrets,
            Database(url.get_secret_value(), pooled=secrets.database_url_pooled is not None),
            TelegramClient(secrets.require("telegram_bot_token"), timeout=TELEGRAM_TIMEOUT_SECONDS),
            dispatcher,
        )
    return _runtime


@app.post("/api/telegram")
async def telegram_update(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> Response:
    rt = runtime()
    expected = rt.secrets.require("telegram_webhook_secret")
    if not hmac.compare_digest((x_telegram_bot_api_secret_token or "").encode(), expected.encode()):
        return Response(status_code=401)
    try:
        payload: Any = await request.json()
        update = Update.model_validate(payload)
    except (ValueError, ValidationError):
        return Response(status_code=200)
    ctx = BotContext(
        rt.db,
        rt.settings,
        rt.secrets,
        rt.secrets.owner_id(),
        datetime.now(UTC),
        rt.dispatcher,
        rt.telegram,
    )
    await handle_update(update, ctx, rt.telegram)
    return Response(status_code=200)


@app.get("/api/health")
async def health() -> dict[str, bool]:
    return {"ok": True}
