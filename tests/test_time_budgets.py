"""Time limits that only work together: Vercel's function limit, Telegram timeouts, deadlines."""

from __future__ import annotations

import json
from pathlib import Path

from lens.bot.commands.status import RESEND_DEADLINE_SECONDS
from lens.delivery.sender import SEND_DEADLINE_SECONDS
from lens.storage.cycles import STALE_SENDING
from lens.webhook import TELEGRAM_TIMEOUT_SECONDS

CYCLE_TELEGRAM_TIMEOUT_SECONDS = 15.0


def test_a_held_resend_finishes_inside_the_vercel_function_limit() -> None:
    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
    limit = config["functions"]["api/telegram.py"]["maxDuration"]
    # The callback answer, the last chunk started before the deadline, and the reply.
    assert limit >= RESEND_DEADLINE_SECONDS + 3 * TELEGRAM_TIMEOUT_SECONDS


def test_a_live_send_is_never_mistaken_for_a_dead_one() -> None:
    longest_send = SEND_DEADLINE_SECONDS + 3 * CYCLE_TELEGRAM_TIMEOUT_SECONDS
    assert STALE_SENDING.total_seconds() > 2 * longest_send
