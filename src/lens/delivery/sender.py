"""The delivery state machine: send the chunks not yet accepted, then settle SENT, HELD or FAILED."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from lens.delivery.telegram import (
    MessageSender,
    TelegramAmbiguousError,
    TelegramDefiniteError,
    TelegramRateLimitedError,
)
from lens.storage.cycles import CycleRepo, DeliveryState
from lens.storage.db import Database

SEND_DEADLINE_SECONDS = 90.0
MAX_RATE_LIMIT_WAIT = 30.0


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    state: DeliveryState
    sent_chunks: int
    error_class: str | None = None


async def deliver(
    db: Database,
    telegram: MessageSender,
    *,
    delivery_id: int,
    chat_id: int,
    chunks: list[str],
    allowed: frozenset[DeliveryState],
    clock: Callable[[], datetime],
    final_state: DeliveryState = DeliveryState.SENT,
) -> DeliveryResult:
    """Claim the delivery, send every chunk without a message id, and record each one as it lands.

    A definite failure before any chunk was accepted leaves the delivery FAILED, so a later run
    may retry. Anything that might have reached Telegram leaves it HELD for the owner to review.
    """
    async with db.session() as session:
        token = await CycleRepo(session).claim_delivery(delivery_id, allowed=allowed, now=clock())
        message_ids = await CycleRepo(session).delivery_message_ids(delivery_id)
    if token is None:
        return DeliveryResult(DeliveryState.SENDING, 0, "claim_refused")
    if len(message_ids) != len(chunks):
        message_ids = [None] * len(chunks)
    started = time.monotonic()
    sent = 0
    for index, text in enumerate(chunks):
        if message_ids[index] is not None:
            continue
        while True:
            try:
                message_id = await telegram.send_message(chat_id, text)
                break
            except TelegramRateLimitedError as error:
                remaining = SEND_DEADLINE_SECONDS - (time.monotonic() - started)
                if error.retry_after > min(MAX_RATE_LIMIT_WAIT, remaining):
                    return await _settle(
                        db,
                        delivery_id,
                        token,
                        clock,
                        sent,
                        any(m is not None for m in message_ids),
                        type(error).__name__,
                    )
                await asyncio.sleep(error.retry_after)
            except TelegramDefiniteError as error:
                return await _settle(
                    db,
                    delivery_id,
                    token,
                    clock,
                    sent,
                    any(m is not None for m in message_ids),
                    type(error).__name__,
                )
            except TelegramAmbiguousError as error:
                async with db.session() as session:
                    await CycleRepo(session).finish_delivery(
                        delivery_id, token, DeliveryState.HELD, clock(), type(error).__name__
                    )
                return DeliveryResult(DeliveryState.HELD, sent, type(error).__name__)
        message_ids[index] = message_id
        sent += 1
        async with db.session() as session:
            await CycleRepo(session).record_chunk(delivery_id, token, index, message_id)
    async with db.session() as session:
        await CycleRepo(session).finish_delivery(delivery_id, token, final_state, clock())
    return DeliveryResult(final_state, sent)


async def _settle(
    db: Database,
    delivery_id: int,
    token: uuid.UUID,
    clock: Callable[[], datetime],
    sent: int,
    partially_delivered: bool,
    error_class: str,
) -> DeliveryResult:
    state = DeliveryState.HELD if partially_delivered else DeliveryState.FAILED
    async with db.session() as session:
        await CycleRepo(session).finish_delivery(delivery_id, token, state, clock(), error_class)
    return DeliveryResult(state, sent, error_class)
