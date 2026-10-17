"""Command registry and dispatch. The owner guard runs before any handler, for every update."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from lens.bot.updates import Update, is_owner_private
from lens.delivery.telegram import MessageSender
from lens.logs import get_logger
from lens.settings import Secrets, Settings
from lens.storage.db import Database
from lens.storage.ops import OpsRepo

log = get_logger("lens.bot")


class Messenger(MessageSender, Protocol):
    async def answer_callback(self, callback_id: str, text: str = "") -> None: ...


class Dispatcher(Protocol):
    async def dispatch(self, workflow: str, inputs: dict[str, str]) -> None: ...


@dataclass(frozen=True, slots=True)
class Button:
    label: str
    data: str


@dataclass(slots=True)
class Reply:
    messages: list[str]
    buttons: list[list[Button]] = field(default_factory=list)

    @classmethod
    def text(cls, text: str, buttons: list[list[Button]] | None = None) -> Reply:
        return cls([text], buttons or [])


@dataclass(slots=True)
class BotContext:
    db: Database
    settings: Settings
    secrets: Secrets
    owner_id: int
    now: datetime
    dispatcher: Dispatcher | None = None
    messenger: Messenger | None = None


Handler = Callable[[BotContext, list[str]], Awaitable[Reply]]
ActionHandler = Callable[[BotContext, dict[str, Any]], Awaitable[Reply]]


@dataclass(frozen=True, slots=True)
class Command:
    name: str
    usage: str
    summary: str
    handler: Handler


COMMANDS: dict[str, Command] = {}
ACTIONS: dict[str, ActionHandler] = {}


def command(name: str, usage: str, summary: str) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        if name in COMMANDS:
            raise ValueError(f"duplicate command /{name}")
        COMMANDS[name] = Command(name, usage, summary, handler)
        return handler

    return register


def action(kind: str) -> Callable[[ActionHandler], ActionHandler]:
    def register(handler: ActionHandler) -> ActionHandler:
        ACTIONS[kind] = handler
        return handler

    return register


def parse_command(text: str) -> tuple[str, list[str]] | None:
    if not text.startswith("/"):
        return None
    head, *args = text.strip().split()
    name = head[1:].split("@", 1)[0].lower()
    return name, args


def markup(buttons: list[list[Button]]) -> dict[str, Any] | None:
    if not buttons:
        return None
    return {
        "inline_keyboard": [
            [{"text": b.label, "callback_data": b.data} for b in row] for row in buttons
        ]
    }


async def offer(
    ctx: BotContext, kind: str, payload: dict[str, Any], label: str
) -> list[list[Button]]:
    """A one-tap confirmation button plus Cancel. The token is used once, then it is gone."""
    async with ctx.db.session() as session:
        token = await OpsRepo(session).create_action(ctx.owner_id, kind, payload, ctx.now)
    return [[Button(label, f"a:{token}"), Button("Cancel", "cancel")]]


async def consume(ctx: BotContext, data: str) -> Reply:
    if data == "cancel":
        return Reply.text("Cancelled. Nothing was recorded.")
    if not data.startswith("a:"):
        return Reply.text("That button is not recognised.")
    async with ctx.db.session() as session:
        found = await OpsRepo(session).consume_action(data[2:], ctx.owner_id, ctx.now)
    if found is None:
        return Reply.text("That button was already used or has expired. Nothing was changed.")
    kind, payload = found
    handler = ACTIONS.get(kind)
    if handler is None:
        return Reply.text("That action is no longer supported.")
    return await handler(ctx, payload)


async def _send(messenger: Messenger, chat_id: int, reply: Reply) -> None:
    for index, text in enumerate(reply.messages):
        last = index == len(reply.messages) - 1
        await messenger.send_message(
            chat_id, text, reply_markup=markup(reply.buttons) if last else None
        )


async def handle_update(update: Update, ctx: BotContext, messenger: Messenger) -> bool:
    """Route one update. Returns False when the guard dropped it; nothing is read or sent then."""
    if not is_owner_private(update, ctx.owner_id):
        return False
    try:
        if update.callback_query is not None:
            query = update.callback_query
            await messenger.answer_callback(query.id)
            reply = await consume(ctx, query.data or "")
        else:
            assert update.message is not None
            parsed = parse_command(update.message.text or "")
            if parsed is None:
                reply = Reply.text("Send a command, for example /today or /help.")
            else:
                name, args = parsed
                found = COMMANDS.get(name)
                reply = (
                    (await found.handler(ctx, args))
                    if found
                    else Reply.text(f"Unknown command /{name}. Try /help.")
                )
    except Exception as error:
        error_id = secrets.token_hex(4)
        log.exception("bot handler failed", error_id=error_id, error=type(error).__name__)
        reply = Reply.text(f"Something went wrong (error {error_id}). The details are in the logs.")
    await _send(messenger, ctx.owner_id, reply)
    return True
