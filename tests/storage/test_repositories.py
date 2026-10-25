from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from lens.domain.instruments import AssetClass, Instrument
from lens.domain.portfolio import FxRate, TxKind
from lens.storage.cycles import STALE_SENDING, ClaimOutcome, CycleRepo, DeliveryState
from lens.storage.db import Database
from lens.storage.ledger import LedgerRepo
from lens.storage.market import MarketRepo
from lens.storage.ops import OpsRepo
from tests.helpers import make_bars

pytestmark = pytest.mark.db

OWNER = 42
DAY = date(2026, 10, 16)
NOW = datetime(2026, 10, 15, 23, 0, tzinfo=UTC)
AAPL = Instrument.create("AAPL", AssetClass.STOCK, "Apple")


async def _owner(db: Database) -> None:
    async with db.session() as s:
        await MarketRepo(s).ensure_owner(OWNER, "MYR", "Asia/Kuala_Lumpur")


async def test_two_racing_cycles_produce_one_claim(db: Database) -> None:
    """Scenario 14 at the lock level."""
    await _owner(db)

    async def claim() -> ClaimOutcome:
        async with db.session() as s:
            return (await CycleRepo(s).claim_day(OWNER, DAY, NOW)).outcome

    outcomes = await asyncio.gather(claim(), claim(), claim())
    assert sorted(outcomes) == sorted(
        [ClaimOutcome.CLAIMED, ClaimOutcome.IN_PROGRESS, ClaimOutcome.IN_PROGRESS]
    )


async def test_done_day_reports_already_done_and_stale_claim_is_adopted(db: Database) -> None:
    await _owner(db)
    async with db.session() as s:
        first = await CycleRepo(s).claim_day(OWNER, DAY, NOW)
    async with db.session() as s:
        stale = await CycleRepo(s).claim_day(OWNER, DAY, NOW + timedelta(minutes=45))
    assert stale.outcome is ClaimOutcome.CLAIMED
    assert first.token is not None
    async with db.session() as s:
        # the first holder lost the claim, so its release is ignored
        assert not await CycleRepo(s).release_day(OWNER, DAY, first.token, "DONE", NOW)
        assert stale.token is not None
        assert await CycleRepo(s).release_day(OWNER, DAY, stale.token, "DONE", NOW)
    async with db.session() as s:
        assert (
            await CycleRepo(s).claim_day(OWNER, DAY, NOW + timedelta(hours=2))
        ).outcome is ClaimOutcome.ALREADY_DONE


async def test_racing_ai_reservations_never_exceed_the_budget(db: Database) -> None:
    await _owner(db)

    async def reserve() -> int | None:
        async with db.session() as s:
            return await OpsRepo(s).reserve_ai(
                owner_id=OWNER,
                day=DAY,
                model="m",
                amount=Decimal("0.20"),
                max_calls=10,
                budget_usd=Decimal("0.50"),
            )

    results = await asyncio.gather(*(reserve() for _ in range(6)))
    assert sum(r is not None for r in results) == 2
    async with db.session() as s:
        usage = await OpsRepo(s).usage(OWNER, DAY)
    assert usage.committed_usd == Decimal("0.40")


async def test_settled_cost_replaces_the_reservation_and_unknown_keeps_it(db: Database) -> None:
    await _owner(db)
    async with db.session() as s:
        ops = OpsRepo(s)
        a = await ops.reserve_ai(
            owner_id=OWNER,
            day=DAY,
            model="m",
            amount=Decimal("0.20"),
            max_calls=10,
            budget_usd=Decimal(1),
        )
        b = await ops.reserve_ai(
            owner_id=OWNER,
            day=DAY,
            model="m",
            amount=Decimal("0.20"),
            max_calls=10,
            budget_usd=Decimal(1),
        )
        assert a is not None
        assert b is not None
        await ops.settle_ai(
            a,
            status="SETTLED",
            now=NOW,
            input_tokens=1000,
            output_tokens=200,
            cost_usd=Decimal("0.008"),
        )
        await ops.settle_ai(b, status="UNKNOWN", now=NOW, error_class="ReadTimeout")
    async with db.session() as s:
        usage = await OpsRepo(s).usage(OWNER, DAY)
    assert usage.committed_usd == Decimal("0.208")
    assert usage.unknown == 1


async def test_confirmation_is_used_exactly_once(db: Database) -> None:
    await _owner(db)
    async with db.session() as s:
        token = await OpsRepo(s).create_action(OWNER, "transaction", {"kind": "BUY"}, NOW)

    async def tap() -> object:
        async with db.session() as s:
            return await OpsRepo(s).consume_action(token, OWNER, NOW + timedelta(minutes=1))

    results = await asyncio.gather(tap(), tap(), tap())
    assert sum(r is not None for r in results) == 1
    async with db.session() as s:
        assert await OpsRepo(s).consume_action(token, 999, NOW) is None


async def test_delivered_briefing_is_never_replaced(db: Database) -> None:
    await _owner(db)
    async with db.session() as s:
        stored = await CycleRepo(s).save_briefing(
            owner_id=OWNER,
            day=DAY,
            run_id=None,
            mode="deterministic",
            document={"v": 1},
            chunks=["a", "b"],
            inputs={},
            code_version="x",
        )
        assert stored.delivery_id is not None
        token = await CycleRepo(s).claim_delivery(
            stored.delivery_id, allowed=frozenset({DeliveryState.COMPOSED}), now=NOW
        )
        assert token is not None
        await CycleRepo(s).record_chunk(stored.delivery_id, token, 0, 101)
        await CycleRepo(s).record_chunk(stored.delivery_id, token, 1, 102)
        await CycleRepo(s).finish_delivery(stored.delivery_id, token, DeliveryState.SENT, NOW)
    async with db.session() as s:
        again = await CycleRepo(s).save_briefing(
            owner_id=OWNER,
            day=DAY,
            run_id=None,
            mode="deterministic",
            document={"v": 2},
            chunks=["c"],
            inputs={},
            code_version="x",
        )
    assert again.document == {"v": 1}
    assert again.delivery_state is DeliveryState.SENT
    assert again.message_ids == [101, 102]


async def test_held_resend_can_only_be_claimed_once(db: Database) -> None:
    await _owner(db)
    async with db.session() as s:
        stored = await CycleRepo(s).save_briefing(
            owner_id=OWNER,
            day=DAY,
            run_id=None,
            mode="deterministic",
            document={},
            chunks=["a"],
            inputs={},
            code_version="x",
        )
        assert stored.delivery_id is not None
        token = await CycleRepo(s).claim_delivery(
            stored.delivery_id, allowed=frozenset({DeliveryState.COMPOSED}), now=NOW
        )
        assert token is not None
        await CycleRepo(s).finish_delivery(
            stored.delivery_id, token, DeliveryState.HELD, NOW, "ReadTimeout"
        )
    delivery_id = stored.delivery_id

    async def resend() -> object:
        async with db.session() as s:
            return await CycleRepo(s).claim_delivery(
                delivery_id, allowed=frozenset({DeliveryState.HELD}), now=NOW
            )

    results = await asyncio.gather(resend(), resend())
    assert sum(r is not None for r in results) == 1


async def test_a_sending_delivery_is_held_only_after_the_cutoff(db: Database) -> None:
    await _owner(db)
    async with db.session() as s:
        stored = await CycleRepo(s).save_briefing(
            owner_id=OWNER,
            day=DAY,
            run_id=None,
            mode="deterministic",
            document={},
            chunks=["a", "b"],
            inputs={},
            code_version="x",
        )
        assert stored.delivery_id is not None
        token = await CycleRepo(s).claim_delivery(
            stored.delivery_id, allowed=frozenset({DeliveryState.COMPOSED}), now=NOW
        )
        assert token is not None
        await CycleRepo(s).record_chunk(stored.delivery_id, token, 0, 777)

    async with db.session() as s:
        assert await CycleRepo(s).hold_stale_sending(NOW + STALE_SENDING, owner_id=OWNER) == 0
    async with db.session() as s:
        late = NOW + STALE_SENDING + timedelta(seconds=1)
        assert await CycleRepo(s).hold_stale_sending(late, owner_id=OWNER) == 1
    async with db.session() as s:
        held = await CycleRepo(s).held_deliveries(OWNER)
        assert [b.message_ids for b in held] == [[777, None]]
        with pytest.raises(RuntimeError, match="claim lost"):
            await CycleRepo(s).record_chunk(stored.delivery_id, token, 1, 778)


async def test_bar_revision_is_recorded_and_bars_round_trip(db: Database) -> None:
    await _owner(db)
    bars = make_bars("AAPL", [100, 101, 102])
    async with db.session() as s:
        repo = MarketRepo(s)
        ids = await repo.ensure_instruments([AAPL])
        assert await repo.upsert_bars(ids["AAPL"], bars) == 0
        revised = [*bars[:2], replace(bars[2], close=Decimal(99))]
        assert await repo.upsert_bars(ids["AAPL"], revised) == 1
    async with db.session() as s:
        loaded = (await MarketRepo(s).load_bars(["AAPL"]))["AAPL"]
    assert [b.close for b in loaded] == [Decimal(100), Decimal(101), Decimal(99)]


async def test_fx_lookup_uses_the_latest_rate_on_or_before(db: Database) -> None:
    async with db.session() as s:
        repo = MarketRepo(s)
        await repo.save_fx(FxRate("USD", "MYR", Decimal("4.40"), date(2026, 10, 14), "bnm"))
        await repo.save_fx(FxRate("USD", "MYR", Decimal("4.42"), date(2026, 10, 16), "bnm"))
    async with db.session() as s:
        rate = await MarketRepo(s).latest_fx("USD", "MYR", date(2026, 10, 15))
    assert rate is not None
    assert (rate.rate, rate.day) == (Decimal("4.40"), date(2026, 10, 14))


async def test_ledger_round_trip(db: Database) -> None:
    await _owner(db)
    async with db.session() as s:
        ids = await MarketRepo(s).ensure_instruments([AAPL])
        await LedgerRepo(s).add(
            OWNER,
            ids["AAPL"],
            kind=TxKind.BUY,
            day=DAY,
            currency="USD",
            quantity=Decimal(10),
            price=Decimal("101.5"),
            fee=Decimal(1),
        )
    async with db.session() as s:
        txs = await LedgerRepo(s).transactions(OWNER)
    assert [(t.symbol, t.kind, t.quantity, t.price) for t in txs] == [
        ("AAPL", TxKind.BUY, Decimal(10), Decimal("101.5"))
    ]
