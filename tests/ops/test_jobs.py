"""Backfill and close-based alerts, with fake providers and a fake Telegram."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, ClassVar

import pytest

from lens.domain.instruments import AssetClass, Instrument
from lens.domain.portfolio import TxKind
from lens.ops import jobs
from lens.settings import Secrets, load_settings
from lens.storage.db import Database
from lens.storage.ledger import LedgerRepo
from lens.storage.market import MarketRepo
from lens.storage.ops import OpsRepo
from tests.pipeline.factories import asset, asset_data_from, make_inputs
from tests.pipeline.test_cycle import FakeCollector

pytestmark = pytest.mark.db
NOW = datetime(2026, 10, 16, 9, 45, tzinfo=UTC)


class FakeTelegram:
    sent: ClassVar[list[str]] = []

    def __init__(self, token: str) -> None:
        FakeTelegram.sent = []

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> int:
        FakeTelegram.sent.append(text)
        return 1

    async def close(self) -> None:
        return None


def _secrets(url: str) -> Secrets:
    return Secrets(
        _env_file=None,
        database_url_direct=url,
        owner_telegram_id=42,  # type: ignore[call-arg]
        telegram_bot_token="123456789:test-token-not-real-xxxxxxxxxxxxxxx",
    )


async def test_backfill_stores_history_and_reports_readiness(
    db: Database, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = asset_data_from(make_inputs())
    monkeypatch.setattr(jobs, "_collector", lambda settings, secrets, now: FakeCollector(data))
    async with db.session() as session:
        await MarketRepo(session).ensure_owner(42, "MYR", "Asia/Kuala_Lumpur")
        await MarketRepo(session).set_watched(42, Instrument.create("SPY", AssetClass.ETF), True)
    text = await jobs.backfill(load_settings(), _secrets(migrated_url), "spy", NOW)
    assert text.startswith("Backfill finished for SPY: 260/200 verified sessions, ready.")
    async with db.session() as session:
        assert len((await MarketRepo(session).load_bars(["SPY"]))["SPY"]) == 260
    assert (await jobs.backfill(load_settings(), _secrets(migrated_url), "ZZZZ", NOW)).startswith(
        "ZZZZ is not known"
    )


async def test_exit_review_alerts_once_per_episode_in_immediate_mode(
    db: Database, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    falling = [100.0 * 1.002**i for i in range(240)] + [100.0 * 0.92**i for i in range(1, 21)]
    inputs = make_inputs(assets=(asset("AAPL", AssetClass.STOCK, falling, name="Apple"),))
    monkeypatch.setattr(
        jobs, "_collector", lambda settings, secrets, now: FakeCollector(asset_data_from(inputs))
    )
    monkeypatch.setattr(jobs, "TelegramClient", FakeTelegram)
    async with db.session() as session:
        market = MarketRepo(session)
        await market.ensure_owner(42, "MYR", "Asia/Kuala_Lumpur")
        ids = await market.ensure_instruments([Instrument.create("AAPL", AssetClass.STOCK)])
        await LedgerRepo(session).add(
            42,
            ids["AAPL"],
            kind=TxKind.BUY,
            day=date(2026, 6, 1),
            currency="USD",
            quantity=Decimal(5),
            price=Decimal(150),
        )
    settings = load_settings()
    assert (
        await jobs.holding_alerts(settings, _secrets(migrated_url), NOW) == []
    )  # digest mode: silent

    async with db.session() as session:
        await OpsRepo(session).set_preference(42, alerts_mode="immediate")
    first = await jobs.holding_alerts(settings, _secrets(migrated_url), NOW)
    second = await jobs.holding_alerts(settings, _secrets(migrated_url), NOW)
    assert len(first) == 1
    assert first[0].startswith("<b>EXIT</b> review for AAPL")
    assert second == []
