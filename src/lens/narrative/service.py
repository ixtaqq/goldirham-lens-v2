"""Optional narrative: count, reserve, call, settle, verify. Any failure means no narrative."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, cast

from pydantic import ValidationError

from lens.domain.facts import build_catalog
from lens.logs import get_logger
from lens.narrative.prompt import SYSTEM, user_message
from lens.narrative.schema import JSON_SCHEMA, NarrativeOutput
from lens.narrative.verifier import VerificationError, verify
from lens.pipeline.analysis import analyze
from lens.pipeline.compose import compose
from lens.pipeline.inputs import CycleInputs, NarrativeIn
from lens.settings import Secrets, Settings
from lens.storage.db import Database
from lens.storage.ops import OpsRepo

log = get_logger("lens.narrative")
MILLION = Decimal(1_000_000)


class NarrativeError(RuntimeError):
    """The narrative is skipped; the deterministic briefing goes out unchanged."""


class BudgetRefusedError(NarrativeError):
    pass


class ModelRefusedError(NarrativeError):
    pass


class UnverifiedError(NarrativeError):
    pass


class _Messages(Protocol):
    async def count_tokens(self, **kwargs: Any) -> Any: ...

    async def create(self, **kwargs: Any) -> Any: ...


class ModelClient(Protocol):
    @property
    def messages(self) -> _Messages: ...


def default_client(api_key: str, timeout: float) -> ModelClient:
    from anthropic import AsyncAnthropic

    return cast(ModelClient, AsyncAnthropic(api_key=api_key, max_retries=0, timeout=timeout))


def cost(settings: Settings, input_tokens: int, output_tokens: int) -> Decimal:
    n = settings.narrative
    return (
        Decimal(input_tokens) * n.input_usd_per_mtok
        + Decimal(output_tokens) * n.output_usd_per_mtok
    ) / MILLION


async def narrate(
    settings: Settings,
    secrets: Secrets,
    inputs: CycleInputs,
    db: Database,
    client: ModelClient | None = None,
) -> NarrativeIn:
    n = settings.narrative
    if n.rates_verified_on is None:
        raise NarrativeError("token rates are not verified; set narrative.rates_verified_on")
    doc = compose(inputs, analyze(inputs))
    async with db.session() as session:
        prefs = await OpsRepo(session).preferences(inputs.owner_id)
    facts = build_catalog(doc, include_position_values=prefs.narrative_include_positions)
    names = {a.symbol: a.name for a in inputs.assets}
    holdings = {h.symbol: h.name for h in doc.portfolio.holdings} if doc.portfolio else {}
    setups = {s.symbol: s.name for s in doc.setups}
    messages = [{"role": "user", "content": user_message(doc, facts, names)}]
    model = client or default_client(
        secrets.require("anthropic_api_key"), float(n.deadline_seconds)
    )

    counted = await model.messages.count_tokens(model=n.model, system=SYSTEM, messages=messages)
    reserve = cost(settings, int(counted.input_tokens), n.max_output_tokens)
    now = datetime.now(UTC)
    async with db.session() as session:
        reservation = await OpsRepo(session).reserve_ai(
            owner_id=inputs.owner_id,
            day=now.date(),
            model=n.model,
            amount=reserve,
            max_calls=n.max_calls_per_day,
            budget_usd=n.daily_budget_usd,
        )
    if reservation is None:
        raise BudgetRefusedError("daily AI limit reached")

    async def settle(status: str, response: Any = None, error: str | None = None) -> None:
        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "input_tokens", None)
        tokens_out = getattr(usage, "output_tokens", None)
        spent = (
            cost(settings, tokens_in, tokens_out)
            if isinstance(tokens_in, int) and isinstance(tokens_out, int)
            else None
        )
        async with db.session() as session:
            # Without reported usage the cost is unknown, so the reservation stays committed.
            await OpsRepo(session).settle_ai(
                reservation,
                status=status if spent is not None else "UNKNOWN",
                now=datetime.now(UTC),
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                cost_usd=spent,
                error_class=error,
            )

    try:
        response = await asyncio.wait_for(
            model.messages.create(
                model=n.model,
                max_tokens=n.max_output_tokens,
                system=SYSTEM,
                messages=messages,
                output_config={
                    "effort": n.effort,
                    "format": {"type": "json_schema", "schema": JSON_SCHEMA},
                },
            ),
            timeout=n.deadline_seconds,
        )
    except Exception as error:
        # A timeout or transport error may still have been billed: keep the reservation.
        await settle("UNKNOWN", error=type(error).__name__)
        raise NarrativeError(type(error).__name__) from error

    if response.stop_reason == "refusal":
        await settle("SETTLED", response, "refusal")
        raise ModelRefusedError("model declined")
    if response.stop_reason == "max_tokens":
        await settle("SETTLED", response, "max_tokens")
        raise NarrativeError("output truncated")
    text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
    try:
        output = NarrativeOutput.model_validate_json(text or "")
        paragraphs = verify(output, facts, holdings=holdings, setups=setups, names=names)
    except (ValidationError, VerificationError) as error:
        await settle("SETTLED", response, type(error).__name__)
        reason = error.rejection.value if isinstance(error, VerificationError) else "schema"
        log.warning("narrative rejected", rejection=reason)
        raise UnverifiedError(reason) from error
    await settle("SETTLED", response)
    return NarrativeIn(paragraphs=tuple(paragraphs), model=n.model)
