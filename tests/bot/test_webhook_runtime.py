"""A real webhook request: secret check, update parsing, command, Telegram reply."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from lens import webhook
from lens.storage.db import Database
from lens.storage.market import MarketRepo

pytestmark = pytest.mark.db

TOKEN = "123456789:test-token-not-real-xxxxxxxxxxxxxxx"
SECRET = "webhook-secret-for-tests"


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, migrated_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL_POOLED", migrated_url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "42")
    monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "github_pat_test")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/goldirham-lens-v2")
    monkeypatch.setattr(webhook, "_runtime", None)


def _update(text: str) -> dict[str, object]:
    return {
        "update_id": 9,
        "message": {
            "message_id": 3,
            "from": {"id": 42},
            "chat": {"id": 42, "type": "private"},
            "text": text,
        },
    }


@respx.mock
def test_help_command_round_trip(configured: None, db: Database) -> None:
    send = respx.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    )
    with TestClient(webhook.app) as client:
        response = client.post(
            "/api/telegram",
            json=_update("/help"),
            headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
        )
    assert response.status_code == 200
    payload = json.loads(send.calls.last.request.read())
    assert payload["chat_id"] == 42
    assert "/why TICKER" in payload["text"]


@respx.mock
def test_run_dispatches_the_daily_workflow(configured: None, db: Database) -> None:
    respx.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    )
    dispatch = respx.post(
        "https://api.github.com/repos/owner/goldirham-lens-v2/actions/workflows/daily.yml/dispatches"
    ).mock(return_value=httpx.Response(204))
    with TestClient(webhook.app) as client:
        client.post(
            "/api/telegram",
            json=_update("/run"),
            headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
        )
    request = dispatch.calls.last.request
    assert request.headers["Authorization"] == "Bearer github_pat_test"
    assert json.loads(request.read()) == {"ref": "main", "inputs": {"trigger": "dispatch"}}


@respx.mock
def test_malformed_update_is_acknowledged_without_reply(configured: None, db: Database) -> None:
    send = respx.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage")
    with TestClient(webhook.app) as client:
        response = client.post(
            "/api/telegram",
            content=b"not json",
            headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
        )
    assert response.status_code == 200
    assert not send.called


@respx.mock
async def test_watchlist_add_starts_a_backfill(configured: None, db: Database) -> None:
    async with db.session() as session:
        await MarketRepo(session).ensure_owner(42, "MYR", "Asia/Kuala_Lumpur")
    respx.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    )
    dispatch = respx.post(
        "https://api.github.com/repos/owner/goldirham-lens-v2/actions/workflows/backfill.yml/dispatches"
    ).mock(return_value=httpx.Response(204))
    from datetime import UTC, datetime

    from lens.bot.router import BotContext, handle_update
    from lens.bot.updates import Update

    rt = webhook.runtime()
    ctx = BotContext(db, rt.settings, rt.secrets, 42, datetime.now(UTC), rt.dispatcher, rt.telegram)
    await handle_update(Update.model_validate(_update("/watchlist add AMD")), ctx, rt.telegram)
    assert json.loads(dispatch.calls.last.request.read())["inputs"] == {"symbol": "AMD"}
    async with db.session() as session:
        watched = [i.symbol for i in await MarketRepo(session).watchlist(42)]
    assert "AMD" in watched
