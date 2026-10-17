"""Narrative service with a fake model client: budget, refusal, unknown outcomes, verification."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from lens.narrative.service import (
    BudgetRefusedError,
    ModelRefusedError,
    NarrativeError,
    UnverifiedError,
    narrate,
)
from lens.settings import Secrets, load_settings
from lens.storage.db import Database
from lens.storage.market import MarketRepo
from lens.storage.ops import OpsRepo
from tests.narrative.test_verifier import INPUTS, SPY_CHANGE

pytestmark = pytest.mark.db


@dataclass
class Block:
    text: str
    type: str = "text"


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass
class Response:
    content: list[Block]
    stop_reason: str = "end_turn"
    usage: Usage = field(default_factory=lambda: Usage(3000, 250))


@dataclass
class Counted:
    input_tokens: int = 3000


@dataclass
class FakeMessages:
    reply: Response | Exception
    created: list[dict[str, Any]] = field(default_factory=list)

    async def count_tokens(self, **kwargs: Any) -> Counted:
        return Counted()

    async def create(self, **kwargs: Any) -> Response:
        self.created.append(kwargs)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@dataclass
class FakeClient:
    messages: FakeMessages


def _settings(**narrative: Any) -> Any:
    base = load_settings()
    return base.model_copy(
        update={
            "narrative": base.narrative.model_copy(
                update={"enabled": True, "rates_verified_on": date(2026, 10, 16), **narrative}
            )
        }
    )


def _ok() -> Response:
    payload = {
        "market": [f"SPDR S&P 500 ETF moved {{{{f:{SPY_CHANGE}}}}}."],
        "holdings": [],
        "setups": [],
        "caveat": "uncertainty",
    }
    return Response([Block(json.dumps(payload))])


SECRETS = Secrets(_env_file=None, anthropic_api_key="sk-ant-test-not-real-key")  # type: ignore[call-arg]


async def _owner(db: Database) -> None:
    async with db.session() as session:
        await MarketRepo(session).ensure_owner(INPUTS.owner_id, "MYR", "Asia/Kuala_Lumpur")


async def test_unverified_rates_make_no_call(db: Database) -> None:
    await _owner(db)
    client = FakeClient(FakeMessages(_ok()))
    with pytest.raises(NarrativeError, match="rates"):
        await narrate(_settings(rates_verified_on=None), SECRETS, INPUTS, db, client)
    assert client.messages.created == []


async def test_grounded_narrative_settles_actual_cost(db: Database) -> None:
    await _owner(db)
    client = FakeClient(FakeMessages(_ok()))
    result = await narrate(_settings(), SECRETS, INPUTS, db, client)
    assert result.paragraphs[0].startswith("SPDR S&P 500 ETF moved ")
    request = client.messages.created[0]
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert "tool_choice" not in request
    assert "temperature" not in request
    async with db.session() as session:
        usage = await OpsRepo(session).usage(INPUTS.owner_id, datetime.now(UTC).date())
    # 3000 in at $4/M + 250 out at $20/M
    assert usage.committed_usd == Decimal("0.017")


async def test_budget_refusal_makes_no_call(db: Database) -> None:
    await _owner(db)
    client = FakeClient(FakeMessages(_ok()))
    with pytest.raises(BudgetRefusedError):
        await narrate(_settings(daily_budget_usd=Decimal("0.001")), SECRETS, INPUTS, db, client)
    assert client.messages.created == []


async def test_model_refusal_falls_back_without_narrative(db: Database) -> None:
    await _owner(db)
    client = FakeClient(FakeMessages(Response([], stop_reason="refusal")))
    with pytest.raises(ModelRefusedError):
        await narrate(_settings(), SECRETS, INPUTS, db, client)


async def test_timeout_keeps_the_reservation_as_unknown(db: Database) -> None:
    await _owner(db)
    client = FakeClient(FakeMessages(TimeoutError()))
    with pytest.raises(NarrativeError):
        await narrate(_settings(), SECRETS, INPUTS, db, client)
    async with db.session() as session:
        usage = await OpsRepo(session).usage(INPUTS.owner_id, datetime.now(UTC).date())
    assert usage.unknown == 1
    assert usage.committed_usd > 0


async def test_output_with_a_number_is_rejected_and_still_billed(db: Database) -> None:
    """Scenario 8: 'rose 5%' never reaches the briefing."""
    await _owner(db)
    leaked = {
        "market": ["SPY rose 5% today."],
        "holdings": [],
        "setups": [],
        "caveat": "uncertainty",
    }
    client = FakeClient(FakeMessages(Response([Block(json.dumps(leaked))])))
    with pytest.raises(UnverifiedError, match="ungrounded_number"):
        await narrate(_settings(), SECRETS, INPUTS, db, client)
    async with db.session() as session:
        usage = await OpsRepo(session).usage(INPUTS.owner_id, datetime.now(UTC).date())
    assert usage.committed_usd == Decimal("0.017")
