"""The daily cycle: claim the day, gather, analyse, persist, compose, render, store, deliver."""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

from sqlalchemy.exc import DBAPIError, OperationalError

from lens.data.collect import Collector, provider_factories
from lens.delivery.chunker import chunk
from lens.delivery.renderer import TELEGRAM_LIMIT, render_sections
from lens.delivery.sender import deliver
from lens.delivery.telegram import TelegramClient, TelegramError
from lens.logs import get_logger
from lens.ops.health import ping
from lens.pipeline.analysis import Analysis, analyze
from lens.pipeline.compose import compose
from lens.pipeline.gather import External, Gathered, gather
from lens.pipeline.inputs import AssetIn, BarIn, ContextIn, CycleInputs, NarrativeIn, pack
from lens.pipeline.persist import persist_analysis, persist_calls, persist_market
from lens.settings import Secrets, Settings
from lens.storage.cycles import ClaimOutcome, CycleRepo, DeliveryState
from lens.storage.db import Database
from lens.storage.market import MarketRepo
from lens.storage.ops import OpsRepo

log = get_logger("lens.pipeline.cycle")
T = TypeVar("T")
REPO_ROOT = Path(__file__).resolve().parents[3]


class Outcome(StrEnum):
    SENT = "sent"
    HELD = "held"
    FAILED = "failed"
    ALREADY_DONE = "already_done"
    IN_PROGRESS = "in_progress"
    PREVIEW = "preview"
    DEGRADED_SENT = "degraded_sent"
    DEGRADED_SKIPPED = "degraded_skipped"


EXIT_CODES = {
    Outcome.SENT: 0,
    Outcome.HELD: 0,
    Outcome.ALREADY_DONE: 0,
    Outcome.IN_PROGRESS: 0,
    Outcome.PREVIEW: 0,
    Outcome.DEGRADED_SENT: 3,
    Outcome.DEGRADED_SKIPPED: 0,
    Outcome.FAILED: 1,
}


@dataclass(slots=True)
class CycleResult:
    outcome: Outcome
    briefing_date: date
    chunks: list[str] = field(default_factory=list)
    detail: str = ""


def code_version() -> str:
    if sha := os.environ.get("GITHUB_SHA"):
        return sha[:40]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 - git from PATH
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip()[:40] or "local"
    except OSError:
        return "local"


def migration_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head


def local_day(settings: Settings, now: datetime) -> tuple[date, bool]:
    return settings.owner.today(now), settings.owner.is_late(now)


@dataclass(slots=True)
class CycleDeps:
    """Seams for tests: how to reach the database, Telegram and the providers."""

    database: Callable[[str, bool], Database] = lambda url, rollback: Database(
        url, rollback_only=rollback
    )
    telegram: Callable[[str], TelegramClient] = TelegramClient
    collector: Callable[[Settings, Secrets, datetime], Collector] = lambda settings, secrets, now: (
        Collector(
            settings,
            now,
            factories=provider_factories(
                secrets.alpha_vantage_api_key.get_secret_value()
                if secrets.alpha_vantage_api_key
                else None
            ),
        )
    )
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    state_dir: Path = Path(".lens-state")
    external: External = field(default_factory=External)
    chunk_limit: int = TELEGRAM_LIMIT


async def _stage[T](
    db: Database,
    run_id: int,
    name: str,
    clock: Callable[[], datetime],
    action: Callable[[], Awaitable[T]],
) -> T:
    started = clock()
    try:
        result = await action()
    except Exception as error:
        async with db.session() as session:
            await CycleRepo(session).record_stage(
                run_id, name, started, clock(), "failed", type(error).__name__
            )
        raise
    async with db.session() as session:
        await CycleRepo(session).record_stage(run_id, name, started, clock(), "ok")
    return result


async def _narrate(
    settings: Settings, secrets: Secrets, inputs: CycleInputs, db: Database
) -> NarrativeIn | None:
    if not settings.narrative.enabled or secrets.anthropic_api_key is None:
        return None
    from lens.narrative.service import NarrativeError, narrate

    try:
        return await narrate(settings, secrets, inputs, db)
    except NarrativeError as error:
        log.warning("narrative skipped", reason=type(error).__name__)
        return None


def render(inputs: CycleInputs, limit: int = TELEGRAM_LIMIT) -> tuple[list[str], dict[str, object]]:
    document = compose(inputs, analyze(inputs))
    return chunk(render_sections(document), limit), document.model_dump(mode="json")


async def run_cycle(
    settings: Settings,
    secrets: Secrets,
    *,
    trigger: str,
    dry_run: bool = False,
    github_run_id: str | None = None,
    deps: CycleDeps | None = None,
) -> CycleResult:
    deps = deps or CycleDeps()
    now = deps.clock()
    briefing_date, late = local_day(settings, now)
    owner_id = secrets.owner_id()
    healthcheck = (
        None
        if dry_run or secrets.healthcheck_ping_url is None
        else secrets.healthcheck_ping_url.get_secret_value()
    )
    await ping(healthcheck, "start")

    db = deps.database(secrets.require("database_url_direct"), dry_run)
    try:
        await db.ping()
        revision = await db.revision()
    except (OSError, OperationalError, DBAPIError) as error:
        await db.dispose()
        log.error("database unreachable", error=type(error).__name__)
        return await run_degraded(
            settings,
            secrets,
            reason="The database was unreachable.",
            trigger=trigger,
            dry_run=dry_run,
            deps=deps,
            healthcheck=healthcheck,
        )
    if revision != migration_head():
        await db.dispose()
        return await run_degraded(
            settings,
            secrets,
            trigger=trigger,
            dry_run=dry_run,
            deps=deps,
            healthcheck=healthcheck,
            reason="The database schema is behind the code. Run the migrate workflow.",
        )

    try:
        if dry_run:
            gathered = await gather(
                db,
                settings,
                now=now,
                briefing_date=briefing_date,
                owner_id=owner_id,
                cycle_id=str(uuid.uuid4()),
                trigger=trigger,
                late=late,
                collector=deps.collector(settings, secrets, now),
                persist_reference_data=False,
                external=deps.external,
            )
            chunks, _ = render(gathered.inputs, deps.chunk_limit)
            return CycleResult(Outcome.PREVIEW, briefing_date, chunks)
        return await _scheduled(
            settings,
            secrets,
            db,
            deps,
            trigger=trigger,
            now=now,
            briefing_date=briefing_date,
            late=late,
            owner_id=owner_id,
            github_run_id=github_run_id,
            healthcheck=healthcheck,
        )
    finally:
        await db.dispose()


async def _scheduled(
    settings: Settings,
    secrets: Secrets,
    db: Database,
    deps: CycleDeps,
    *,
    trigger: str,
    now: datetime,
    briefing_date: date,
    late: bool,
    owner_id: int,
    github_run_id: str | None,
    healthcheck: str | None,
) -> CycleResult:
    async with db.session() as session:
        await MarketRepo(session).ensure_owner(
            owner_id, settings.owner.base_currency, settings.owner.timezone
        )
        claim = await CycleRepo(session).claim_day(owner_id, briefing_date, now)
    if claim.outcome is not ClaimOutcome.CLAIMED:
        outcome = (
            Outcome.ALREADY_DONE
            if claim.outcome is ClaimOutcome.ALREADY_DONE
            else Outcome.IN_PROGRESS
        )
        log.info("cycle skipped", outcome=outcome.value, briefing_date=briefing_date.isoformat())
        if outcome is Outcome.ALREADY_DONE:
            await ping(healthcheck)
        return CycleResult(outcome, briefing_date, detail="today's briefing is already handled")
    assert claim.token is not None
    cycle_id = uuid.uuid4()
    async with db.session() as session:
        run_id = await CycleRepo(session).start_run(
            cycle_id=cycle_id,
            owner_id=owner_id,
            day=briefing_date,
            trigger=trigger,
            github_run_id=github_run_id,
            code_version=code_version(),
            now=now,
        )
    clock = deps.clock
    try:
        gathered: Gathered = await _stage(
            db,
            run_id,
            "gather",
            clock,
            lambda: gather(
                db,
                settings,
                now=now,
                briefing_date=briefing_date,
                owner_id=owner_id,
                cycle_id=str(cycle_id),
                trigger=trigger,
                late=late,
                collector=deps.collector(settings, secrets, now),
                external=deps.external,
            ),
        )
        inputs = gathered.inputs
        analysis = await _stage(db, run_id, "analyze", clock, _async(lambda: analyze(inputs)))
        await _stage(
            db, run_id, "persist", clock, lambda: _persist_all(db, gathered, analysis, run_id)
        )
        narrative = await _stage(
            db, run_id, "narrate", clock, lambda: _narrate(settings, secrets, inputs, db)
        )
        if narrative is not None:
            inputs = inputs.model_copy(update={"narrative": narrative})
        chunks, document = await _stage(
            db, run_id, "compose", clock, _async(lambda: render(inputs, deps.chunk_limit))
        )
        async with db.session() as session:
            stored = await CycleRepo(session).save_briefing(
                owner_id=owner_id,
                day=briefing_date,
                run_id=run_id,
                mode=str(document["mode"]),
                document=document,
                chunks=chunks,
                inputs=pack(inputs),
                code_version=code_version(),
            )
        delivery_id = stored.delivery_id
        assert delivery_id is not None
        telegram = deps.telegram(secrets.require("telegram_bot_token"))
        try:
            result = await _stage(
                db,
                run_id,
                "deliver",
                clock,
                lambda: deliver(
                    db,
                    telegram,
                    delivery_id=delivery_id,
                    chat_id=owner_id,
                    chunks=stored.chunks,
                    allowed=frozenset({DeliveryState.COMPOSED, DeliveryState.FAILED}),
                    clock=clock,
                ),
            )
        finally:
            await telegram.close()
    except Exception as error:
        await _fail(
            db,
            secrets,
            deps,
            run_id=run_id,
            owner_id=owner_id,
            day=briefing_date,
            token=claim.token,
            error=error,
            healthcheck=healthcheck,
        )
        raise
    state = "DONE" if result.state in (DeliveryState.SENT, DeliveryState.HELD) else "FAILED"
    async with db.session() as session:
        await CycleRepo(session).finish_run(run_id, result.state.value, clock(), result.error_class)
        await CycleRepo(session).release_day(owner_id, briefing_date, claim.token, state, clock())
    if result.state is DeliveryState.SENT:
        await ping(healthcheck)
        return CycleResult(Outcome.SENT, briefing_date, stored.chunks)
    if result.state is DeliveryState.HELD:
        async with db.session() as session:
            await OpsRepo(session).record_event(
                kind="delivery_held",
                severity="warning",
                source="deliver",
                dedupe_key=f"held:{briefing_date}",
                details={"error": result.error_class},
            )
        await ping(healthcheck)
        return CycleResult(Outcome.HELD, briefing_date, stored.chunks, result.error_class or "")
    await ping(healthcheck, "fail", body=f"delivery failed: {result.error_class}")
    return CycleResult(Outcome.FAILED, briefing_date, stored.chunks, result.error_class or "")


async def _persist_all(db: Database, gathered: Gathered, analysis: Analysis, run_id: int) -> None:
    await persist_market(db, gathered.data)
    await persist_analysis(db, gathered.inputs, analysis, run_id)
    await persist_calls(db, run_id, gathered.calls)


def _async[T](fn: Callable[[], T]) -> Callable[[], Awaitable[T]]:
    async def run() -> T:
        return fn()

    return run


async def _fail(
    db: Database,
    secrets: Secrets,
    deps: CycleDeps,
    *,
    run_id: int,
    owner_id: int,
    day: date,
    token: uuid.UUID,
    error: BaseException,
    healthcheck: str | None,
) -> None:
    now = deps.clock()
    try:
        async with db.session() as session:
            await CycleRepo(session).finish_run(run_id, "FAILED", now, type(error).__name__)
            await CycleRepo(session).release_day(owner_id, day, token, "FAILED", now)
            first = await OpsRepo(session).record_event(
                kind="cycle_failed",
                severity="error",
                source="cycle",
                dedupe_key=f"cycle_failed:{day}",
                details={"error": type(error).__name__},
            )
    except Exception:
        first = True
    await ping(healthcheck, "fail", body=f"{type(error).__name__}")
    if first:
        await notify_owner(
            secrets,
            deps,
            f"Goldirham Lens: today's briefing failed ({type(error).__name__}). "
            "The next scheduled run will retry. Run details are in GitHub Actions.",
        )


async def notify_owner(secrets: Secrets, deps: CycleDeps, text: str) -> bool:
    if secrets.telegram_bot_token is None or secrets.owner_telegram_id is None:
        return False
    telegram = deps.telegram(secrets.telegram_bot_token.get_secret_value())
    try:
        await telegram.send_message(secrets.owner_telegram_id, text)
        return True
    except TelegramError as error:
        log.warning("owner alert failed", error=type(error).__name__)
        return False
    finally:
        await telegram.close()


async def run_degraded(
    settings: Settings,
    secrets: Secrets,
    *,
    reason: str,
    trigger: str,
    dry_run: bool,
    deps: CycleDeps,
    healthcheck: str | None,
) -> CycleResult:
    """Build a briefing from live data alone, send it once per day, and report the outage."""
    now = deps.clock()
    briefing_date, late = local_day(settings, now)
    marker = deps.state_dir / f"degraded-sent-{briefing_date.isoformat()}"
    if marker.exists() and not dry_run:
        return CycleResult(
            Outcome.DEGRADED_SKIPPED, briefing_date, detail="degraded briefing already sent"
        )
    collector = deps.collector(settings, secrets, now)
    data = await collector.collect_all(list(settings.instruments()))
    inputs = CycleInputs(
        briefing_date=briefing_date,
        generated_at=now,
        cycle_id=str(uuid.uuid4()),
        trigger=trigger,
        mode="degraded",
        degraded_reason=f"{reason} Portfolio, signals and setups need the database and are skipped today.",
        late=late,
        owner_id=secrets.owner_id(),
        base_currency=settings.owner.base_currency,
        detail=settings.owner.detail,
        risk_per_trade_pct=settings.risk.risk_per_trade_pct,
        settings=settings.model_dump(mode="json"),
        active_versions=(),
        assets=tuple(
            AssetIn(
                symbol=d.instrument.symbol,
                name=d.instrument.name,
                asset_class=d.instrument.asset_class,
                market=d.instrument.market,
                currency=d.instrument.currency,
                watched=True,
                closed_sessions=d.closed_sessions,
                bars=tuple(BarIn.of(b) for b in d.bars),
                readiness=d.readiness.reasons,
                primary=d.primary,
                cross_check=d.cross_check,
                errors=d.errors,
            )
            for d in data.values()
        ),
        signals=(),
        transactions=(),
        fx=(),
        fundamentals=(),
        previous=None,
        previous_reviews={},
        context=ContextIn(),
        sources_unavailable=("database",),
    )
    chunks, _ = render(inputs, deps.chunk_limit)
    if dry_run:
        return CycleResult(Outcome.PREVIEW, briefing_date, chunks, reason)
    telegram = deps.telegram(secrets.require("telegram_bot_token"))
    accepted = 0
    try:
        for text in chunks:
            await telegram.send_message(secrets.owner_id(), text)
            accepted += 1
    except TelegramError as error:
        if accepted == 0 and error.definite:
            await ping(healthcheck, "fail", body=f"degraded send failed: {type(error).__name__}")
            return CycleResult(Outcome.FAILED, briefing_date, chunks, type(error).__name__)
        # Part of it may have reached the owner; the marker stops the next trigger resending it.
        reason = f"{reason} Delivery stopped after {accepted} message(s) ({type(error).__name__})."
    finally:
        await telegram.close()
    deps.state_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(now.isoformat(), encoding="utf-8")
    await ping(healthcheck, "fail", body=reason)
    return CycleResult(Outcome.DEGRADED_SENT, briefing_date, chunks, reason)
