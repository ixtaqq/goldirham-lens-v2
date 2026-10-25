"""Degraded mode needs no database, so these run without PostgreSQL."""

from __future__ import annotations

from pathlib import Path

import pytest

from lens.delivery.telegram import TelegramAmbiguousError, TelegramDefiniteError, TelegramError
from lens.pipeline.cycle import Outcome, run_degraded
from lens.settings import load_settings
from tests.pipeline.test_cycle import FakeTelegram, _deps, _secrets

UNUSED_DATABASE = "postgresql+asyncpg://lens:unused@127.0.0.1:1/lens_test"


async def _degraded(telegram: FakeTelegram, tmp_path: Path, trigger: str) -> Outcome:
    result = await run_degraded(
        load_settings(),
        _secrets(UNUSED_DATABASE),
        reason="The database was unreachable.",
        trigger=trigger,
        dry_run=False,
        deps=_deps(UNUSED_DATABASE, telegram, tmp_path, chunk_limit=400),
        healthcheck=None,
    )
    return result.outcome


@pytest.mark.parametrize(
    ("fail_on", "error"),
    [
        (2, TelegramDefiniteError("HTTP 400")),
        (1, TelegramAmbiguousError("ReadTimeout")),
    ],
    ids=["definite-after-first-chunk", "ambiguous-on-first-chunk"],
)
async def test_a_degraded_briefing_that_may_have_arrived_is_never_resent(
    tmp_path: Path, fail_on: int, error: TelegramError
) -> None:
    telegram = FakeTelegram(fail_on={fail_on: error})
    first = await _degraded(telegram, tmp_path, "schedule_1")
    calls_after_first = telegram.calls
    second = await _degraded(telegram, tmp_path, "schedule_2")

    assert first is Outcome.DEGRADED_SENT
    assert second is Outcome.DEGRADED_SKIPPED
    assert telegram.calls == calls_after_first


async def test_a_definite_failure_before_any_chunk_lets_the_next_trigger_retry(
    tmp_path: Path,
) -> None:
    telegram = FakeTelegram(fail_on={1: TelegramDefiniteError("HTTP 400")})
    first = await _degraded(telegram, tmp_path, "schedule_1")
    second = await _degraded(telegram, tmp_path, "schedule_2")

    assert first is Outcome.FAILED
    assert second is Outcome.DEGRADED_SENT
    assert telegram.sent
