"""Owner guard, webhook secret, command coverage, and ledger confirmations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

import lens.bot.commands  # noqa: F401
from lens import webhook
from lens.bot.commands.ledger import InputError, parse_transaction
from lens.bot.router import COMMANDS, BotContext, handle_update
from lens.bot.updates import Update
from lens.domain.portfolio import TxKind
from lens.settings import Secrets, load_settings
from lens.storage.db import Database
from lens.storage.ledger import LedgerRepo
from lens.storage.market import MarketRepo

OWNER = 42
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)


@dataclass
class FakeMessenger:
    sent: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)

    async def send_message(
        self, chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None
    ) -> int:
        assert chat_id == OWNER
        self.sent.append((text, reply_markup))
        return len(self.sent)

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        return None


def message(
    text: str, *, sender: int = OWNER, chat: int = OWNER, chat_type: str = "private"
) -> Update:
    return Update.model_validate(
        {
            "update_id": 1,
            "message": {
                "message_id": 5,
                "from": {"id": sender},
                "chat": {"id": chat, "type": chat_type},
                "text": text,
            },
        }
    )


def callback(data: str, *, sender: int = OWNER) -> Update:
    return Update.model_validate(
        {
            "update_id": 2,
            "callback_query": {
                "id": "cb",
                "from": {"id": sender},
                "data": data,
                "message": {"message_id": 6, "chat": {"id": OWNER, "type": "private"}},
            },
        }
    )


class ExplodingDb:
    """Any database access fails the test: the guard must stop strangers first."""

    def session(self) -> Any:
        raise AssertionError("handler reached the database for a stranger")


@pytest.mark.parametrize("name", sorted(COMMANDS))
@pytest.mark.parametrize(
    ("sender", "chat", "chat_type"),
    [
        (999, 999, "private"),
        (OWNER, -100, "group"),
        (OWNER, 999, "private"),
        (999, OWNER, "private"),
    ],
)
async def test_every_command_is_guarded(name: str, sender: int, chat: int, chat_type: str) -> None:
    """Scenario 13: no registered command answers anyone but the owner in their private chat."""
    ctx = BotContext(ExplodingDb(), load_settings(), Secrets(_env_file=None), OWNER, NOW)  # type: ignore[arg-type,call-arg]
    messenger = FakeMessenger()
    handled = await handle_update(
        message(f"/{name}", sender=sender, chat=chat, chat_type=chat_type), ctx, messenger
    )
    assert handled is False
    assert messenger.sent == []


async def test_stranger_callback_is_ignored() -> None:
    ctx = BotContext(ExplodingDb(), load_settings(), Secrets(_env_file=None), OWNER, NOW)  # type: ignore[arg-type,call-arg]
    assert await handle_update(callback("a:token", sender=7), ctx, FakeMessenger()) is False


def test_webhook_rejects_a_missing_or_wrong_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario 16: 401 before parsing, logging or touching the database."""

    class Runtime:
        secrets = Secrets(
            _env_file=None, telegram_webhook_secret="right-secret-value", owner_telegram_id=OWNER
        )  # type: ignore[call-arg]
        db = ExplodingDb()

    monkeypatch.setattr(webhook, "runtime", lambda: Runtime())
    client = TestClient(webhook.app)
    assert client.post("/api/telegram", json={"update_id": 1}).status_code == 401
    assert (
        client.post(
            "/api/telegram",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        ).status_code
        == 401
    )
    assert client.get("/api/health").json() == {"ok": True}


@pytest.mark.parametrize(
    ("kind", "args", "message_part"),
    [
        (TxKind.BUY, ["AAPL"], "Usage"),
        (TxKind.BUY, ["AAPL", "-1", "100"], "quantity must be positive"),
        (TxKind.BUY, ["AAPL", "1", "abc"], "price must be a number"),
        (TxKind.BUY, ["AAPL", "1", "NaN"], "price must be a number"),
        (TxKind.BUY, ["AAPL", "1", "100", "2", "2099-01-01"], "past"),
        (TxKind.SPLIT, ["NVDA", "0"], "ratio must be positive"),
    ],
)
def test_invalid_ledger_input_is_explained(
    kind: TxKind, args: list[str], message_part: str
) -> None:
    with pytest.raises(InputError, match=message_part):
        parse_transaction(kind, args, date(2026, 10, 16))


def test_buy_parses_fee_and_date() -> None:
    assert parse_transaction(
        TxKind.BUY, ["aapl", "10", "1,234.5", "1.2", "2026-10-01"], date(2026, 10, 16)
    ) == {
        "symbol": "AAPL",
        "kind": "BUY",
        "quantity": "10",
        "price": "1234.5",
        "fee": "1.2",
        "day": "2026-10-01",
    }


@pytest.mark.db
async def test_buy_confirms_once_and_records_once(db: Database) -> None:
    async with db.session() as session:
        await MarketRepo(session).ensure_owner(OWNER, "MYR", "Asia/Kuala_Lumpur")
    ctx = BotContext(db, load_settings(), Secrets(_env_file=None), OWNER, NOW)  # type: ignore[call-arg]
    messenger = FakeMessenger()
    await handle_update(message("/buy AAPL 10 150 1"), ctx, messenger)
    text, markup = messenger.sent[-1]
    assert "Please confirm" in text
    assert markup is not None
    confirm = markup["inline_keyboard"][0][0]["callback_data"]
    async with db.session() as session:
        assert await LedgerRepo(session).transactions(OWNER) == []

    await handle_update(callback(confirm), ctx, messenger)
    await handle_update(callback(confirm), ctx, messenger)
    assert messenger.sent[-2][0].startswith("Recorded.")
    assert "already used" in messenger.sent[-1][0]
    async with db.session() as session:
        transactions = await LedgerRepo(session).transactions(OWNER)
    assert len(transactions) == 1


@pytest.mark.db
async def test_overselling_is_refused_before_confirmation(db: Database) -> None:
    async with db.session() as session:
        await MarketRepo(session).ensure_owner(OWNER, "MYR", "Asia/Kuala_Lumpur")
    ctx = BotContext(db, load_settings(), Secrets(_env_file=None), OWNER, NOW)  # type: ignore[call-arg]
    messenger = FakeMessenger()
    await handle_update(message("/sell AAPL 5 150"), ctx, messenger)
    assert messenger.sent[-1][0].startswith("Not recorded:")
    assert messenger.sent[-1][1] is None


@pytest.mark.db
async def test_handler_failure_returns_a_sanitised_error_id(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = BotContext(db, load_settings(), Secrets(_env_file=None), OWNER, NOW)  # type: ignore[call-arg]

    async def boom(ctx: BotContext, args: list[str]) -> Any:
        raise RuntimeError("secret detail postgresql://user:pass@host/db")

    monkeypatch.setitem(
        COMMANDS, "today", COMMANDS["today"].__class__("today", "/today", "x", boom)
    )
    messenger = FakeMessenger()
    await handle_update(message("/today"), ctx, messenger)
    text = messenger.sent[-1][0]
    assert text.startswith("Something went wrong (error ")
    assert "pass" not in text
