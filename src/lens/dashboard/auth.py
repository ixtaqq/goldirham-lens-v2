"""Owner sign-in: Telegram Login Widget data verified on the server, then a signed session cookie.

Telegram signs the widget's fields with HMAC-SHA256, keyed by SHA-256 of the bot token. Only the
owner's Telegram id is accepted, and only for a few minutes after Telegram signed it.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from datetime import datetime, timedelta

COOKIE = "lens_session"
LOGIN_MAX_AGE = timedelta(minutes=10)
CLOCK_SKEW = timedelta(seconds=60)
SESSION_MAX_AGE = timedelta(hours=12)
MIN_SECRET_LENGTH = 32


def _sign(key: bytes, message: str) -> str:
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


def verify_login(
    fields: Mapping[str, str], *, bot_token: str, owner_id: int, now: datetime
) -> bool:
    received = fields.get("hash")
    if not received:
        return False
    data = {k: v for k, v in fields.items() if k != "hash"}
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    expected = _sign(hashlib.sha256(bot_token.encode()).digest(), check)
    if not hmac.compare_digest(expected, received):
        return False
    try:
        signed_at = datetime.fromtimestamp(int(data["auth_date"]), now.tzinfo)
        user_id = int(data["id"])
    except (KeyError, ValueError, OverflowError):
        return False
    if not -CLOCK_SKEW <= now - signed_at <= LOGIN_MAX_AGE:
        return False
    return user_id == owner_id


def issue_session(owner_id: int, *, secret: str, now: datetime) -> str:
    expires = int((now + SESSION_MAX_AGE).timestamp())
    payload = f"{owner_id}.{expires}"
    return f"{payload}.{_sign(secret.encode(), payload)}"


def read_session(token: str | None, *, secret: str, owner_id: int, now: datetime) -> bool:
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    owner, expires, signature = parts
    if not hmac.compare_digest(_sign(secret.encode(), f"{owner}.{expires}"), signature):
        return False
    try:
        return int(owner) == owner_id and int(expires) > now.timestamp()
    except ValueError:
        return False
