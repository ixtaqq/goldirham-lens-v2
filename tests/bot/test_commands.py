"""Every owner command against a database seeded by a real cycle run."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import lens.bot.commands  # noqa: F401
from lens.bot.router import BotContext, handle_update
from lens.delivery.telegram import TelegramAmbiguousError
from lens.pipeline.cycle import Outcome, run_cycle
from lens.settings import Secrets, load_settings
from lens.storage.db import Database
from lens.storage.ops import OpsRepo
from tests.bot.test_bot import FakeMessenger, callback, message
from tests.pipeline.test_cycle import FakeTelegram, _deps, _secrets

pytestmark = pytest.mark.db
OWNER = 42
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)


async def _seed(
    db: Database, migrated_url: str, tmp_path: Path, telegram: FakeTelegram | None = None
) -> None:
    result = await run_cycle(
        load_settings(),
        _secrets(migrated_url),
        trigger="schedule_1",
        deps=_deps(migrated_url, telegram or FakeTelegram(), tmp_path),
    )
    assert result.outcome in (Outcome.SENT, Outcome.HELD)


async def _say(db: Database, text: str, messenger: FakeMessenger | None = None) -> str:
    out = messenger or FakeMessenger()
    ctx = BotContext(db, load_settings(), Secrets(_env_file=None), OWNER, NOW, None, out)  # type: ignore[call-arg]
    await handle_update(message(text), ctx, out)
    return "\n".join(t for t, _ in out.sent)


async def test_reading_commands_answer_from_stored_results(
    db: Database, migrated_url: str, tmp_path: Path
) -> None:
    assert "No briefing has been stored yet" in await _say(db, "/today")
    await _seed(db, migrated_url, tmp_path)

    assert "<b>Goldirham Lens</b> · Fri 16 Oct 2026" in await _say(db, "/today")
    assert "2026-10-16 · deterministic · sent" in await _say(db, "/briefing")
    assert "<b>Goldirham Lens</b>" in await _say(db, "/briefing 2026-10-16")
    assert "No briefing stored for 2026-10-01" in await _say(db, "/briefing 2026-10-01")

    why = await _say(db, "/why qqq")
    assert "<b>QQQ</b> · session 15 Oct" in why
    assert "✓ medium-term trend is up" in why
    assert "Setup: entry USD" in why
    assert "Not evaluated: the data is not ready." in await _say(db, "/why NVDA")
    assert "No stored decision for TSLA" in await _say(db, "/why TSLA")
    assert "Usage: /why TICKER" in await _say(db, "/why")

    readiness = await _say(db, "/readiness")
    assert "• SPY (15 Oct): ready" in readiness
    assert "• NVDA (15 Oct): fewer verified sessions than required" in readiness

    scorecard = await _say(db, "/scorecard")
    assert "Fewer than 20 resolved signals" in scorecard
    assert "t1_touch_rate: Share of resolved signals" in scorecard
    assert "not live" in await _say(db, "/strategy")


async def test_ledger_flow_portfolio_and_journal(
    db: Database, migrated_url: str, tmp_path: Path
) -> None:
    await _seed(db, migrated_url, tmp_path)
    async with db.session() as session:
        from lens.domain.portfolio import FxRate
        from lens.storage.market import MarketRepo

        await MarketRepo(session).save_fx(FxRate("USD", "MYR", Decimal("4.42"), NOW.date(), "test"))
    messenger = FakeMessenger()
    await _say(db, "/buy SPY 3 600 1 2026-09-01", messenger)
    confirm = messenger.sent[-1][1]["inline_keyboard"][0][0]["callback_data"]  # type: ignore[index]
    ctx = BotContext(db, load_settings(), Secrets(_env_file=None), OWNER, NOW, None, messenger)  # type: ignore[call-arg]
    await handle_update(callback(confirm), ctx, messenger)
    assert messenger.sent[-1][0].startswith("Recorded. Buy 3 SPY at USD 600.00")

    for text in ("/dividend SPY 5", "/fee SPY 1.5", "/split SPY 2 2026-10-01"):
        await _say(db, text, messenger)
        token = messenger.sent[-1][1]["inline_keyboard"][0][0]["callback_data"]  # type: ignore[index]
        await handle_update(callback(token), ctx, messenger)
        assert messenger.sent[-1][0].startswith("Recorded.")
    await handle_update(callback("cancel"), ctx, messenger)
    assert messenger.sent[-1][0] == "Cancelled. Nothing was recorded."

    portfolio = await _say(db, "/portfolio")
    assert portfolio.startswith("<b>Portfolio</b> · MYR ")
    assert "• SPY 6 @ USD" in portfolio
    assert "By currency: USD 100.0%" in portfolio

    assert "Saved your note for SPY" in await _say(db, "/journal note SPY core holding")
    journal = await _say(db, "/journal")
    assert "2026-09-01 BUY SPY 3 @ USD 600.00" in journal
    assert "2026-10-01 SPLIT SPY 2-for-1" in journal
    assert "• SPY: core holding" in journal

    assert "Not recorded: SPY: selling 10 but only 6 held" in await _say(db, "/sell SPY 10 700")
    assert "is not on a supported market" in await _say(db, "/watchlist add 7203.T")
    assert "Removed QQQ" in await _say(db, "/watchlist remove QQQ")
    assert "• QQQ" not in await _say(db, "/watchlist")


async def test_settings_feedback_and_status_commands(
    db: Database, migrated_url: str, tmp_path: Path
) -> None:
    assert "There is no briefing to rate yet." in await _say(db, "/feedback useful")
    await _seed(db, migrated_url, tmp_path)
    assert "Risk per setup is now 0.75%" in await _say(db, "/preferences risk 0.75")
    assert "between 0.1% and 5%" in await _say(db, "/preferences risk 9")
    assert "Briefings will be detailed." in await _say(db, "/preferences detail detailed")
    shown = await _say(db, "/preferences")
    assert "Risk per setup: 0.75%" in shown
    assert "Detail: detailed" in shown
    assert "after each market close" in await _say(db, "/alerts immediate")
    assert "Quiet hours 22:30 to 06:45" in await _say(db, "/alerts quiet 22:30-06:45")
    assert "Recorded 'noisy' for 2026-10-16" in await _say(db, "/feedback noisy too long")
    assert "Only the fact catalog is sent" not in await _say(db, "/privacy")
    assert "AI narrative is off by default" in await _say(db, "/privacy")
    assert "Goldirham Lens is connected" in await _say(db, "/start")
    assert "Unknown command /nope" in await _say(db, "/nope")
    assert "Send a command" in await _say(db, "hello")

    health = await _say(db, "/health")
    assert "On time (by 08:00):" in health
    assert "Last run 2026-10-16 · schedule_1 · sent" in health
    assert "Last backup: none recorded" in health
    async with db.session() as session:
        await OpsRepo(session).record_event(
            kind="backup_ok", severity="info", source="t", dedupe_key="b1"
        )
    assert "Last backup: 20" in await _say(db, "/health")
    usage = await _say(db, "/usage")
    assert "Narrative disabled" in usage
    assert "Calls 0/3" in usage
    assert "Workflow dispatch is not configured" in await _say(db, "/run")


async def test_held_briefing_review_and_resend(
    db: Database, migrated_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "Nothing is held" in await _say(db, "/held")
    from lens.pipeline import cycle as cycle_module

    monkeypatch.setattr(cycle_module, "TELEGRAM_LIMIT", 350, raising=False)
    telegram = FakeTelegram(fail_on={2: TelegramAmbiguousError("ReadTimeout")})
    deps = _deps(migrated_url, telegram, tmp_path, chunk_limit=350)
    result = await run_cycle(
        load_settings(), _secrets(migrated_url), trigger="schedule_1", deps=deps
    )
    assert result.outcome is Outcome.HELD

    messenger = FakeMessenger()
    held = await _say(db, "/held", messenger)
    assert "1 of " in held
    resend_token = messenger.sent[-1][1]["inline_keyboard"][0][0]["callback_data"]  # type: ignore[index]
    ctx = BotContext(db, load_settings(), Secrets(_env_file=None), OWNER, NOW, None, messenger)  # type: ignore[call-arg]
    before = len(messenger.sent)
    await handle_update(callback(resend_token), ctx, messenger)
    resent = messenger.sent[before:]
    assert resent[-1][0].startswith("Resent ")
    assert len(resent) == len(result.chunks) - 1 + 1
    assert "Nothing is held" in await _say(db, "/held")
