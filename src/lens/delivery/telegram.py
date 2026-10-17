"""A thin Telegram Bot API client. Errors are classified so delivery can decide SENT, HELD or FAILED."""

from __future__ import annotations

from typing import Any, Protocol

import httpx

API = "https://api.telegram.org"


class TelegramError(RuntimeError):
    """Base class. `definite` means Telegram certainly did not accept the message."""

    definite = False


class TelegramDefiniteError(TelegramError):
    definite = True


class TelegramRateLimitedError(TelegramError):
    definite = True

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited for {retry_after}s")
        self.retry_after = retry_after


class TelegramAmbiguousError(TelegramError):
    """The request may have been delivered: a timeout or network error after sending."""


class MessageSender(Protocol):
    async def send_message(
        self, chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None
    ) -> int: ...


class TelegramClient:
    def __init__(
        self, token: str, client: httpx.AsyncClient | None = None, timeout: float = 15.0
    ) -> None:
        self._base = f"{API}/bot{token}"
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0))
        self._owns = client is None

    async def close(self) -> None:
        if self._owns:
            await self._client.aclose()

    async def call(self, method: str, payload: dict[str, Any]) -> Any:
        try:
            response = await self._client.post(f"{self._base}/{method}", json=payload)
        except httpx.ConnectError as error:
            raise TelegramDefiniteError(f"connect failed: {type(error).__name__}") from error
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise TelegramAmbiguousError(type(error).__name__) from error
        if response.status_code == 429:
            retry = float(response.json().get("parameters", {}).get("retry_after", 5))
            raise TelegramRateLimitedError(retry)
        if response.status_code >= 500:
            raise TelegramAmbiguousError(f"HTTP {response.status_code}")
        body = response.json()
        if not body.get("ok"):
            raise TelegramDefiniteError(
                f"HTTP {response.status_code}: {str(body.get('description', ''))[:120]}"
            )
        return body["result"]

    async def send_message(
        self, chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None
    ) -> int:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        result = await self.call("sendMessage", payload)
        return int(result["message_id"])

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        await self.call(
            "answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:180]}
        )

    async def get_me(self) -> dict[str, Any]:
        result: dict[str, Any] = await self.call("getMe", {})
        return result

    async def webhook_info(self) -> dict[str, Any]:
        result: dict[str, Any] = await self.call("getWebhookInfo", {})
        return result

    async def set_webhook(self, url: str, secret: str) -> None:
        await self.call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret,
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": True,
            },
        )
