"""Owner sign-in rules: Telegram's signature, the owner's id, freshness, and the session cookie."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import pytest

from lens.dashboard.auth import SESSION_MAX_AGE, issue_session, read_session, verify_login
from lens.dashboard.pages import telegram_html

TOKEN = "123456:test-bot-token-not-real"
OWNER = 42
SECRET = "s" * 40
NOW = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)


def signed(fields: dict[str, str], token: str = TOKEN) -> dict[str, str]:
    """Sign widget fields the way Telegram does."""
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    key = hashlib.sha256(token.encode()).digest()
    return {**fields, "hash": hmac.new(key, check.encode(), hashlib.sha256).hexdigest()}


def login(user: int = OWNER, at: datetime = NOW, **extra: str) -> dict[str, str]:
    return signed(
        {"id": str(user), "first_name": "Owner", "auth_date": str(int(at.timestamp())), **extra}
    )


def test_owner_with_a_fresh_signature_is_accepted() -> None:
    assert verify_login(login(username="owner"), bot_token=TOKEN, owner_id=OWNER, now=NOW)


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param(login(user=7), id="another telegram user"),
        pytest.param(login(at=NOW - timedelta(minutes=11)), id="signed too long ago"),
        pytest.param(login(at=NOW + timedelta(minutes=5)), id="signed in the future"),
        pytest.param({**login(), "first_name": "Mallory"}, id="field changed after signing"),
        pytest.param(
            signed({"id": str(OWNER), "auth_date": str(int(NOW.timestamp()))}, "other:token"),
            id="other bot",
        ),
        pytest.param({k: v for k, v in login().items() if k != "hash"}, id="no hash"),
        pytest.param(signed({"id": str(OWNER)}), id="no auth date"),
        pytest.param(
            signed({"id": "owner", "auth_date": str(int(NOW.timestamp()))}), id="id not a number"
        ),
    ],
)
def test_anything_else_is_refused(fields: dict[str, str]) -> None:
    assert not verify_login(fields, bot_token=TOKEN, owner_id=OWNER, now=NOW)


def test_session_round_trip_and_expiry() -> None:
    token = issue_session(OWNER, secret=SECRET, now=NOW)
    assert read_session(token, secret=SECRET, owner_id=OWNER, now=NOW + timedelta(hours=1))
    assert not read_session(
        token, secret=SECRET, owner_id=OWNER, now=NOW + SESSION_MAX_AGE + timedelta(seconds=1)
    )


@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        "garbage",
        f"{OWNER}.9999999999.{'0' * 64}",
        issue_session(7, secret=SECRET, now=NOW),
        issue_session(OWNER, secret="t" * 40, now=NOW),
        issue_session(OWNER, secret=SECRET, now=NOW).replace(f"{OWNER}.", f"{OWNER}0.", 1),
    ],
)
def test_forged_or_foreign_sessions_are_refused(token: str | None) -> None:
    assert not read_session(token, secret=SECRET, owner_id=OWNER, now=NOW)


def test_stored_telegram_text_keeps_only_bold_italic_and_code() -> None:
    chunk = (
        "<b>KSTL</b> Fear &amp; Greed <i>(Demo)</i> <code>abc</code> &lt;script&gt;x&lt;/script&gt;"
    )
    assert telegram_html(chunk) == (
        "<strong>KSTL</strong> Fear &amp; Greed <em>(Demo)</em> <code>abc</code> &lt;script&gt;x&lt;/script&gt;"
    )
    assert "<script>" not in telegram_html("<script>alert(1)</script><b>ok</b>")
