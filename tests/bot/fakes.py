"""Stand-ins for the database seam, so command handlers run without PostgreSQL."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from lens.bot.router import BotContext, handle_update
from lens.settings import Secrets, load_settings
from tests.bot.test_bot import OWNER, FakeMessenger, callback, message

NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)  # 11:00 MYT


class FakeSession:
    """Answers the few raw queries handlers run themselves, in the order they run them."""

    def __init__(self, scalar: list[Any] | None = None, scalars: list[Any] | None = None) -> None:
        self._scalar = list(scalar or [])
        self._scalars = list(scalars or [])

    async def scalar(self, statement: object) -> Any:
        return self._scalar.pop(0)

    async def scalars(self, statement: object) -> Any:
        return self._scalars.pop(0)


class FakeDb:
    def __init__(self, session: FakeSession | None = None) -> None:
        self.current = session or FakeSession()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[FakeSession]:
        yield self.current


class Repo:
    """Replaces a repository class. Each method returns what the test gave it and is recorded.

    A callable return value is called with the method's arguments.
    """

    def __init__(self, **returns: Any) -> None:
        self.returns = returns
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, session: object) -> Repo:
        return self

    def __getattr__(self, name: str) -> Any:
        if name not in self.returns:
            raise AttributeError(name)

        async def method(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            value = self.returns[name]
            return value(*args, **kwargs) if callable(value) else value

        return method

    def called(self, name: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(a, k) for n, a, k in self.calls if n == name]


class FakeDispatcher:
    def __init__(self) -> None:
        self.dispatched: list[tuple[str, dict[str, str]]] = []

    async def dispatch(self, workflow: str, inputs: dict[str, str]) -> None:
        self.dispatched.append((workflow, inputs))


def context(
    db: FakeDb | None = None,
    *,
    dispatcher: FakeDispatcher | None = None,
    messenger: FakeMessenger | None = None,
    now: datetime = NOW,
) -> BotContext:
    return BotContext(
        db or FakeDb(),  # type: ignore[arg-type]
        load_settings(),
        Secrets(_env_file=None),  # type: ignore[call-arg]
        OWNER,
        now,
        dispatcher,
        messenger or FakeMessenger(),
    )


async def say(ctx: BotContext, text: str) -> str:
    messenger = ctx.messenger
    assert isinstance(messenger, FakeMessenger)
    before = len(messenger.sent)
    await handle_update(message(text), ctx, messenger)
    return "\n".join(t for t, _ in messenger.sent[before:])


async def tap(ctx: BotContext, data: str) -> str:
    messenger = ctx.messenger
    assert isinstance(messenger, FakeMessenger)
    before = len(messenger.sent)
    await handle_update(callback(data), ctx, messenger)
    return "\n".join(t for t, _ in messenger.sent[before:])


def buttons(ctx: BotContext) -> list[str]:
    messenger = ctx.messenger
    assert isinstance(messenger, FakeMessenger)
    markup = messenger.sent[-1][1]
    assert markup is not None
    return [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
