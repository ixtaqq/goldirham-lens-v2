"""End-to-end cycle scenarios against real PostgreSQL, with fake Telegram and fake providers."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from lens.data.collect import AssetData
from lens.data.providers.base import CallLog, ProviderError
from lens.delivery.sender import deliver
from lens.delivery.telegram import TelegramAmbiguousError, TelegramDefiniteError
from lens.domain.briefing import Headline
from lens.domain.instruments import AssetClass, Instrument
from lens.domain.portfolio import FxRate
from lens.pipeline import cycle as cycle_module
from lens.pipeline.cycle import CycleDeps, Outcome, run_cycle
from lens.pipeline.gather import External
from lens.pipeline.replay import compare
from lens.settings import Secrets, load_settings
from lens.storage.cycles import CycleRepo, DeliveryState
from lens.storage.db import Database
from lens.storage.models import Base
from tests.pipeline.factories import asset_data_from, make_inputs

pytestmark = pytest.mark.db

OWNER = 42
NOW = datetime(2026, 10, 15, 23, 1, tzinfo=UTC)  # 07:01 MYT on 16 Oct


@dataclass
class FakeTelegram:
    fail_on: dict[int, Exception] = field(default_factory=dict)
    sent: list[str] = field(default_factory=list)
    calls: int = 0

    async def send_message(
        self, chat_id: int, text_: str, *, reply_markup: dict[str, Any] | None = None
    ) -> int:
        self.calls += 1
        if self.calls in self.fail_on:
            raise self.fail_on[self.calls]
        self.sent.append(text_)
        return 1000 + self.calls

    async def close(self) -> None:
        return None


@dataclass
class SlowTelegram(FakeTelegram):
    delay: float = 0.0

    async def send_message(
        self, chat_id: int, text_: str, *, reply_markup: dict[str, Any] | None = None
    ) -> int:
        await asyncio.sleep(self.delay)
        return await super().send_message(chat_id, text_, reply_markup=reply_markup)


class FakeCollector:
    def __init__(self, data: dict[str, AssetData], error: Exception | None = None) -> None:
        self.data = data
        self.log = CallLog()
        self.error = error

    async def collect_all(
        self, instruments: Sequence[Instrument], stored: object = None
    ) -> dict[str, AssetData]:
        if self.error:
            raise self.error
        return {i.symbol: self.data[i.symbol] for i in instruments if i.symbol in self.data}


async def _fx(currency: str, log: CallLog) -> FxRate:
    return FxRate(currency, "MYR", Decimal("4.42"), NOW.date(), "test")


async def _no_fear(settings: object, log: CallLog) -> object:
    raise ProviderError("alternative.me", "offline in tests", retryable=False)


async def _headlines(settings: object, log: CallLog) -> list[Headline]:
    return [Headline(title="Calm session", source="Test Wire")]


async def _fundamentals(stale: list[Instrument]) -> dict[str, object]:
    return {}


def _deps(
    migrated_url: str,
    telegram: FakeTelegram,
    tmp_path: Path,
    *,
    collector_error: Exception | None = None,
    database_url: str | None = None,
    chunk_limit: int = 4096,
) -> CycleDeps:
    data = asset_data_from(make_inputs())
    return CycleDeps(
        database=lambda url, rollback: Database(
            database_url or migrated_url, rollback_only=rollback
        ),
        telegram=lambda token: telegram,  # type: ignore[arg-type,return-value]
        collector=lambda settings, secrets, now: FakeCollector(data, collector_error),  # type: ignore[arg-type,return-value]
        clock=lambda: NOW,
        state_dir=tmp_path / "state",
        external=External(
            fx=_fx, fear_greed=_no_fear, headlines=_headlines, fundamentals=_fundamentals
        ),  # type: ignore[arg-type]
        chunk_limit=chunk_limit,
    )


def _secrets(url: str) -> Secrets:
    return Secrets(
        _env_file=None,
        database_url_direct=url,
        owner_telegram_id=OWNER,  # type: ignore[call-arg]
        telegram_bot_token="123456789:test-token-not-real-xxxxxxxxxxxxxxx",
    )


async def _counts(db: Database) -> dict[str, int]:
    async with db.engine.connect() as connection:
        return {
            t.name: int(await connection.scalar(text(f'SELECT count(*) FROM "{t.name}"')) or 0)  # noqa: S608
            for t in Base.metadata.sorted_tables
        }


async def test_first_trigger_sends_and_second_exits_without_sending(
    db: Database, migrated_url: str, tmp_path: Path
) -> None:
    """Scenario 7: a later trigger finds the day done and sends nothing."""
    telegram = FakeTelegram()
    settings = load_settings()
    first = await run_cycle(
        settings,
        _secrets(migrated_url),
        trigger="schedule_1",
        deps=_deps(migrated_url, telegram, tmp_path),
    )
    second = await run_cycle(
        settings,
        _secrets(migrated_url),
        trigger="schedule_2",
        deps=_deps(migrated_url, telegram, tmp_path),
    )
    assert first.outcome is Outcome.SENT
    assert second.outcome is Outcome.ALREADY_DONE
    assert telegram.calls == len(first.chunks) >= 1
    assert "Goldirham Lens" in telegram.sent[0]


async def test_two_cycles_started_at_once_produce_one_briefing(
    db: Database, migrated_url: str, tmp_path: Path
) -> None:
    """Scenario 14."""
    telegram = FakeTelegram()
    settings = load_settings()
    results = await asyncio.gather(
        run_cycle(
            settings,
            _secrets(migrated_url),
            trigger="schedule_1",
            deps=_deps(migrated_url, telegram, tmp_path),
        ),
        run_cycle(
            settings,
            _secrets(migrated_url),
            trigger="schedule_2",
            deps=_deps(migrated_url, telegram, tmp_path),
        ),
    )
    assert sorted(r.outcome.value for r in results) == sorted(
        [Outcome.SENT.value, Outcome.IN_PROGRESS.value]
    )
    counts = await _counts(db)
    assert counts["briefings"] == 1
    assert counts["deliveries"] == 1


async def test_timeout_after_chunk_two_holds_and_resend_sends_only_chunk_three(
    db: Database, migrated_url: str, tmp_path: Path
) -> None:
    """Scenario 6."""
    telegram = FakeTelegram(fail_on={3: TelegramAmbiguousError("ReadTimeout")})
    result = await run_cycle(
        load_settings(),
        _secrets(migrated_url),
        trigger="schedule_1",
        deps=_deps(migrated_url, telegram, tmp_path, chunk_limit=350),
    )
    assert result.outcome is Outcome.HELD
    assert len(result.chunks) >= 3
    async with db.session() as session:
        stored = await CycleRepo(session).briefing_on(OWNER, NOW.date().replace(day=16))
    assert stored is not None
    assert stored.delivery_state is DeliveryState.HELD
    assert stored.message_ids[:2] == [1001, 1002]
    assert stored.message_ids[2] is None

    resend = FakeTelegram()
    assert stored.delivery_id is not None
    outcome = await deliver(
        db,
        resend,
        delivery_id=stored.delivery_id,
        chat_id=OWNER,
        chunks=stored.chunks,  # type: ignore[arg-type]
        allowed=frozenset({DeliveryState.HELD}),
        clock=lambda: NOW,
        final_state=DeliveryState.RESENT,
    )
    assert outcome.state is DeliveryState.RESENT
    assert resend.sent == stored.chunks[2:]


async def test_a_run_that_died_mid_send_is_held_by_the_next_trigger(
    db: Database, migrated_url: str, tmp_path: Path
) -> None:
    crashing = FakeTelegram(fail_on={2: RuntimeError("runner killed")})
    with pytest.raises(RuntimeError, match="runner killed"):
        await run_cycle(
            load_settings(),
            _secrets(migrated_url),
            trigger="schedule_1",
            deps=_deps(migrated_url, crashing, tmp_path, chunk_limit=350),
        )

    second = FakeTelegram()
    later = NOW + timedelta(minutes=40)
    result = await run_cycle(
        load_settings(),
        _secrets(migrated_url),
        trigger="schedule_2",
        deps=replace(_deps(migrated_url, second, tmp_path, chunk_limit=350), clock=lambda: later),
    )

    assert result.outcome is Outcome.HELD
    assert second.sent == []
    async with db.session() as session:
        stored = await CycleRepo(session).briefing_on(OWNER, NOW.date().replace(day=16))
    assert stored is not None
    assert stored.delivery_state is DeliveryState.HELD
    assert stored.message_ids[0] == 1001
    assert all(m is None for m in stored.message_ids[1:])


async def test_a_resend_past_its_deadline_stops_and_stays_held(
    db: Database, migrated_url: str, tmp_path: Path
) -> None:
    telegram = FakeTelegram(fail_on={2: TelegramAmbiguousError("ReadTimeout")})
    await run_cycle(
        load_settings(),
        _secrets(migrated_url),
        trigger="schedule_1",
        deps=_deps(migrated_url, telegram, tmp_path, chunk_limit=350),
    )
    async with db.session() as session:
        stored = await CycleRepo(session).briefing_on(OWNER, NOW.date().replace(day=16))
    assert stored is not None
    assert stored.delivery_id is not None
    assert len(stored.chunks) >= 3

    slow = SlowTelegram(delay=0.2)
    outcome = await deliver(
        db,
        slow,
        delivery_id=stored.delivery_id,
        chat_id=OWNER,
        chunks=stored.chunks,
        allowed=frozenset({DeliveryState.HELD}),
        clock=lambda: NOW,
        final_state=DeliveryState.RESENT,
        deadline=0.1,
    )

    assert outcome.state is DeliveryState.HELD
    assert outcome.sent_chunks == 1
    async with db.session() as session:
        after = await CycleRepo(session).briefing_on(OWNER, NOW.date().replace(day=16))
    assert after is not None
    assert after.delivery_state is DeliveryState.HELD
    assert sum(m is not None for m in after.message_ids) == 2


async def test_definite_failure_releases_the_day_for_the_next_trigger(
    db: Database, migrated_url: str, tmp_path: Path
) -> None:
    failing = FakeTelegram(fail_on={1: TelegramDefiniteError("HTTP 400")})
    first = await run_cycle(
        load_settings(),
        _secrets(migrated_url),
        trigger="schedule_1",
        deps=_deps(migrated_url, failing, tmp_path),
    )
    assert first.outcome is Outcome.FAILED
    working = FakeTelegram()
    second = await run_cycle(
        load_settings(),
        _secrets(migrated_url),
        trigger="schedule_2",
        deps=_deps(migrated_url, working, tmp_path),
    )
    assert second.outcome is Outcome.SENT
    assert working.calls == len(second.chunks)


async def test_dry_run_writes_nothing(db: Database, migrated_url: str, tmp_path: Path) -> None:
    telegram = FakeTelegram()
    await run_cycle(
        load_settings(),
        _secrets(migrated_url),
        trigger="schedule_1",
        deps=_deps(migrated_url, telegram, tmp_path),
    )
    before = await _counts(db)
    preview = await run_cycle(
        load_settings(),
        _secrets(migrated_url),
        trigger="manual",
        dry_run=True,
        deps=_deps(migrated_url, telegram, tmp_path),
    )
    assert preview.outcome is Outcome.PREVIEW
    assert preview.chunks
    assert await _counts(db) == before


async def test_stored_briefing_replays_byte_for_byte(
    db: Database, migrated_url: str, tmp_path: Path
) -> None:
    await run_cycle(
        load_settings(),
        _secrets(migrated_url),
        trigger="schedule_1",
        deps=_deps(migrated_url, FakeTelegram(), tmp_path),
    )
    async with db.session() as session:
        stored = await CycleRepo(session).latest_briefing(OWNER)
    assert stored is not None
    result = compare(stored)
    assert result.identical, result.summary


async def test_unreachable_database_sends_one_degraded_briefing(
    migrated_url: str, tmp_path: Path
) -> None:
    """Scenario 5."""
    telegram = FakeTelegram()
    dead = "postgresql+asyncpg://lens:wrong@127.0.0.1:1/lens_test"
    first = await run_cycle(
        load_settings(),
        _secrets(dead),
        trigger="schedule_1",
        deps=_deps(migrated_url, telegram, tmp_path, database_url=dead),
    )
    second = await run_cycle(
        load_settings(),
        _secrets(dead),
        trigger="schedule_2",
        deps=_deps(migrated_url, telegram, tmp_path, database_url=dead),
    )
    assert first.outcome is Outcome.DEGRADED_SENT
    assert second.outcome is Outcome.DEGRADED_SKIPPED
    assert telegram.calls == len(first.chunks)
    assert "Degraded briefing." in telegram.sent[0]


async def test_schema_behind_the_code_goes_degraded(
    db: Database, migrated_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario 17."""
    monkeypatch.setattr(cycle_module, "migration_head", lambda: "9999_future")
    telegram = FakeTelegram()
    result = await run_cycle(
        load_settings(),
        _secrets(migrated_url),
        trigger="schedule_1",
        deps=_deps(migrated_url, telegram, tmp_path),
    )
    assert result.outcome is Outcome.DEGRADED_SENT
    assert "schema is behind the code" in telegram.sent[0]
    assert (await _counts(db))["briefings"] == 0


async def test_failure_alerts_the_owner_once_per_day(
    db: Database, migrated_url: str, tmp_path: Path
) -> None:
    telegram = FakeTelegram()
    for trigger in ("schedule_1", "schedule_2"):
        with pytest.raises(RuntimeError, match="provider exploded"):
            await run_cycle(
                load_settings(),
                _secrets(migrated_url),
                trigger=trigger,
                deps=_deps(
                    migrated_url,
                    telegram,
                    tmp_path,
                    collector_error=RuntimeError("provider exploded"),
                ),
            )
    assert len(telegram.sent) == 1
    assert "today's briefing failed (RuntimeError)" in telegram.sent[0]


async def test_live_strategy_opens_a_signal_and_evaluates_it_the_next_day(
    db: Database, migrated_url: str, tmp_path: Path
) -> None:
    from dataclasses import replace as dc_replace
    from datetime import date as day_type
    from datetime import timedelta

    from lens.domain.bars import Bar
    from lens.pipeline.analysis import strategies_from
    from lens.storage.market import MarketRepo
    from lens.storage.signals import SignalRepo
    from lens.storage.strategies import StrategyRepo

    settings = load_settings()
    pullback = next(s for s in strategies_from(settings) if s.name == "pullback_in_uptrend")
    async with db.session() as session:
        await MarketRepo(session).ensure_owner(OWNER, "MYR", "Asia/Kuala_Lumpur")
        repo = StrategyRepo(session)
        await repo.ensure(pullback)
        await repo.save_report(
            version=pullback.version,
            name=pullback.name,
            params={},
            from_day=day_type(2025, 1, 1),
            to_day=day_type(2026, 10, 15),
            report={},
            report_hash="test",
        )
        await repo.activate(pullback.name, pullback.version, NOW)

    first = await run_cycle(
        settings,
        _secrets(migrated_url),
        trigger="schedule_1",
        deps=_deps(migrated_url, FakeTelegram(), tmp_path),
    )
    assert first.outcome is Outcome.SENT
    assert "<b>QQQ</b> Invesco QQQ" in "\n".join(first.chunks)
    async with db.session() as session:
        open_signals = await SignalRepo(session).open_signals(OWNER)
    assert [s.symbol for s in open_signals] == ["QQQ"]
    stop = open_signals[0].levels.stop

    next_day = NOW + timedelta(days=1)
    data = asset_data_from(make_inputs())
    qqq = data["QQQ"]
    crash_day = day_type(2026, 10, 16)
    last = qqq.bars[-1]
    crash = Bar(
        "QQQ",
        crash_day,
        last.close,
        last.close,
        stop * Decimal("0.98"),
        stop * Decimal("0.99"),
        last.volume,
        "test",
    )
    data["QQQ"] = dc_replace(
        qqq, bars=(*qqq.bars, crash), closed_sessions=(*qqq.closed_sessions, crash_day)
    )
    telegram = FakeTelegram()
    deps = _deps(migrated_url, telegram, tmp_path)
    deps.clock = lambda: next_day
    deps.collector = lambda s, sec, now: FakeCollector(data)  # type: ignore[assignment,return-value]
    second = await run_cycle(settings, _secrets(migrated_url), trigger="schedule_1", deps=deps)
    assert second.outcome is Outcome.SENT
    assert "QQQ stopped out at USD" in "\n".join(second.chunks)
    async with db.session() as session:
        records = {r.signal_day: r for r in await SignalRepo(session).records(OWNER)}
    stopped = records[day_type(2026, 10, 15)]
    assert stopped.status.value == "STOPPED"
    assert stopped.outcome_r is not None
    assert stopped.outcome_r <= -1
    # The rules allow a fresh setup after a stop when trend and trigger still pass; nothing blocks re-entry.
    assert records[crash_day].status.value == "OPEN"


async def test_a_level_alert_fires_in_one_briefing_and_never_again(
    db: Database, migrated_url: str, tmp_path: Path
) -> None:
    from lens.domain.alerts import Direction
    from lens.storage.levels import LevelAlertRepo
    from lens.storage.market import MarketRepo

    spy = Instrument.create("SPY", AssetClass.ETF, "SPDR S&P 500 ETF")
    async with db.session() as session:
        await MarketRepo(session).ensure_owner(OWNER, "MYR", "Asia/Kuala_Lumpur")
        ids = await MarketRepo(session).ensure_instruments([spy])
        await LevelAlertRepo(session).add(
            OWNER, ids["SPY"], Direction.ABOVE, Decimal("600"), NOW.date().replace(month=1, day=2)
        )

    first = await run_cycle(
        load_settings(),
        _secrets(migrated_url),
        trigger="schedule_1",
        deps=_deps(migrated_url, FakeTelegram(), tmp_path),
    )
    tomorrow = NOW + timedelta(days=1)
    second = await run_cycle(
        load_settings(),
        _secrets(migrated_url),
        trigger="schedule_1",
        deps=replace(_deps(migrated_url, FakeTelegram(), tmp_path), clock=lambda: tomorrow),
    )

    assert "<b>Price alerts</b>\n• SPY closed at USD " in "\n".join(first.chunks)
    assert "Price alerts" not in "\n".join(second.chunks)
    async with db.session() as session:
        assert await LevelAlertRepo(session).active(OWNER) == []
        (done,) = await LevelAlertRepo(session).recent(OWNER)
    assert done.triggered_close is not None
    assert done.triggered_close >= Decimal("600")
