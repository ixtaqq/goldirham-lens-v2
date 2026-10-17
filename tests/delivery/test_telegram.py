"""Telegram client error classification decides SENT, HELD or FAILED, so each class is pinned."""

from __future__ import annotations

import httpx
import pytest
import respx

from lens.delivery.telegram import (
    TelegramAmbiguousError,
    TelegramClient,
    TelegramDefiniteError,
    TelegramRateLimitedError,
)

TOKEN = "123456789:test-token-not-real-xxxxxxxxxxxxxxx"
SEND = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


@respx.mock
async def test_send_returns_the_message_id_and_disables_previews() -> None:
    route = respx.post(SEND).mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})
    )
    client = TelegramClient(TOKEN)
    assert await client.send_message(42, "<b>hi</b>") == 77
    body = route.calls.last.request.read().decode()
    assert '"parse_mode":"HTML"' in body
    assert '"is_disabled":true' in body
    await client.close()


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (
            httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 7}}),
            TelegramRateLimitedError,
        ),
        (httpx.Response(502), TelegramAmbiguousError),
        (
            httpx.Response(
                400, json={"ok": False, "description": "Bad Request: can't parse entities"}
            ),
            TelegramDefiniteError,
        ),
        (
            httpx.Response(
                403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"}
            ),
            TelegramDefiniteError,
        ),
    ],
)
@respx.mock
async def test_http_failures_are_classified(
    response: httpx.Response, error: type[Exception]
) -> None:
    respx.post(SEND).mock(return_value=response)
    with pytest.raises(error):
        await TelegramClient(TOKEN).send_message(42, "x")


@respx.mock
async def test_rate_limit_carries_retry_after() -> None:
    respx.post(SEND).mock(
        return_value=httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 7}})
    )
    with pytest.raises(TelegramRateLimitedError) as caught:
        await TelegramClient(TOKEN).send_message(42, "x")
    assert caught.value.retry_after == 7


@respx.mock
async def test_timeout_after_sending_is_ambiguous_but_refused_connection_is_definite() -> None:
    respx.post(SEND).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(TelegramAmbiguousError):
        await TelegramClient(TOKEN).send_message(42, "x")
    respx.post(SEND).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(TelegramDefiniteError):
        await TelegramClient(TOKEN).send_message(42, "x")


@respx.mock
async def test_webhook_registration_and_info() -> None:
    set_route = respx.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True})
    )
    respx.post(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "result": {"url": "https://x.vercel.app/api/telegram"}}
        )
    )
    client = TelegramClient(TOKEN)
    await client.set_webhook("https://x.vercel.app/api/telegram", "secret-value")
    assert '"secret_token":"secret-value"' in set_route.calls.last.request.read().decode()
    assert (await client.webhook_info())["url"].endswith("/api/telegram")
