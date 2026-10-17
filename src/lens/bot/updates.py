"""The small slice of the Telegram Update schema the bot reads, parsed at the boundary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Tg(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)


class User(_Tg):
    id: int


class Chat(_Tg):
    id: int
    type: str


class Message(_Tg):
    message_id: int
    sender: User | None = Field(default=None, alias="from")
    chat: Chat
    text: str | None = None


class CallbackQuery(_Tg):
    id: str
    sender: User = Field(alias="from")
    message: Message | None = None
    data: str | None = None


class Update(_Tg):
    update_id: int
    message: Message | None = None
    callback_query: CallbackQuery | None = None


def is_owner_private(update: Update, owner_id: int) -> bool:
    """True only for the owner, writing in their own private chat."""
    if update.message is not None:
        message = update.message
        return (
            message.sender is not None
            and message.sender.id == owner_id
            and message.chat.type == "private"
            and message.chat.id == owner_id
        )
    if update.callback_query is not None:
        query = update.callback_query
        return (
            query.sender.id == owner_id
            and query.message is not None
            and query.message.chat.type == "private"
            and query.message.chat.id == owner_id
        )
    return False
