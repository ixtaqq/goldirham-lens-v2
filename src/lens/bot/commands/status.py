"""/health, /usage, /held, /run."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select

from lens.bot.router import BotContext, Reply, action, command, offer
from lens.delivery.format import esc, money
from lens.delivery.sender import deliver
from lens.storage.cycles import CycleRepo, DeliveryState
from lens.storage.models import OperationalEvent, PipelineRun, StageRun
from lens.storage.ops import OpsRepo


@command("health", "/health", "On-time rate, last run, provider health, backups")
async def health(ctx: BotContext, args: list[str]) -> Reply:
    today = ctx.now.date()
    async with ctx.db.session() as session:
        cycles = CycleRepo(session)
        week = await cycles.on_time_rate(
            ctx.owner_id, today - timedelta(days=7), deadline_hour_utc=0
        )
        month = await cycles.on_time_rate(
            ctx.owner_id, today - timedelta(days=30), deadline_hour_utc=0
        )
        run = await session.scalar(
            select(PipelineRun)
            .where(PipelineRun.owner_id == ctx.owner_id)
            .order_by(PipelineRun.started_at.desc())
            .limit(1)
        )
        stages = (
            []
            if run is None
            else list(
                await session.scalars(
                    select(StageRun).where(StageRun.run_id == run.id).order_by(StageRun.started_at)
                )
            )
        )
        providers = await OpsRepo(session).provider_health(ctx.now - timedelta(days=1))
        backup = await session.scalar(
            select(OperationalEvent)
            .where(OperationalEvent.kind == "backup_ok")
            .order_by(OperationalEvent.occurred_at.desc())
            .limit(1)
        )
        drill = await session.scalar(
            select(OperationalEvent)
            .where(OperationalEvent.kind.in_(["restore_drill_ok", "restore_drill_failed"]))
            .order_by(OperationalEvent.occurred_at.desc())
            .limit(1)
        )
    lines = [
        "<b>Health</b>",
        f"On time (by 08:00): last 7 days {week[0]}/{week[1]} · last 30 days {month[0]}/{month[1]}",
    ]
    if run is not None:
        lines.append(
            f"Last run {run.briefing_date.isoformat()} · {esc(run.trigger)} · {esc(run.status.lower())}"
        )
        for stage in stages:
            seconds = (stage.finished_at - stage.started_at).total_seconds()
            lines.append(f"   {esc(stage.stage)} {seconds:.1f}s {esc(stage.outcome)}")
    if providers:
        lines.append(
            "Providers (24h): "
            + " · ".join(
                f"{esc(p)} {calls - failures}/{calls}"
                + (f" p95 {p95}ms" if p95 is not None else "")
                for p, calls, failures, p95 in providers
            )
        )
    lines.append(
        f"Last backup: {backup.occurred_at:%Y-%m-%d %H:%M} UTC"
        if backup
        else "Last backup: none recorded"
    )
    if drill:
        result = "passed" if drill.kind == "restore_drill_ok" else "FAILED"
        lines.append(f"Last restore drill: {result} {drill.occurred_at:%Y-%m-%d}")
    else:
        lines.append("Last restore drill: none recorded")
    return Reply.text("\n".join(lines))


@command("usage", "/usage", "Today's AI ledger: reserved, settled, unknown, budget left")
async def usage(ctx: BotContext, args: list[str]) -> Reply:
    narrative = ctx.settings.narrative
    async with ctx.db.session() as session:
        summary = await OpsRepo(session).usage(ctx.owner_id, ctx.now.date())
    verified = (
        narrative.rates_verified_on.isoformat() if narrative.rates_verified_on else "not verified"
    )
    lines = [
        "<b>AI usage today (UTC)</b>",
        f"Narrative {'enabled' if narrative.enabled else 'disabled'} · model {esc(narrative.model)}",
        f"Calls {summary.calls}/{narrative.max_calls_per_day} · committed {money(summary.committed_usd, 'USD')} "
        f"of {money(narrative.daily_budget_usd, 'USD')} · unknown outcomes {summary.unknown}",
        f"Rates last verified: {verified}",
    ]
    return Reply.text("\n".join(lines))


@command("held", "/held", "Review briefings whose delivery was uncertain")
async def held(ctx: BotContext, args: list[str]) -> Reply:
    async with ctx.db.session() as session:
        briefings = await CycleRepo(session).held_deliveries(ctx.owner_id)
    if not briefings:
        return Reply.text("Nothing is held. Every briefing was delivered or definitely failed.")
    stored = briefings[0]
    sent = sum(m is not None for m in stored.message_ids)
    preview = esc(stored.chunks[0][:600]) if stored.chunks else ""
    resend = await offer(
        ctx, "held_resend", {"delivery_id": stored.delivery_id}, "Resend remaining"
    )
    dismiss = await offer(ctx, "held_dismiss", {"delivery_id": stored.delivery_id}, "Dismiss")
    buttons = [[resend[0][0], dismiss[0][0]]]
    text = (
        f"<b>Held briefing</b> {stored.briefing_date.isoformat()}\n"
        f"{sent} of {len(stored.chunks)} messages were accepted before delivery became uncertain. "
        f"Resend sends only the {len(stored.chunks) - sent} not yet accepted.\n\n<pre>{preview}</pre>"
    )
    return Reply.text(text, buttons)


@action("held_resend")
async def held_resend(ctx: BotContext, payload: dict[str, Any]) -> Reply:
    """Resend only the chunks Telegram has not accepted, through the same state machine."""
    delivery_id = int(payload["delivery_id"])
    async with ctx.db.session() as session:
        stored = await CycleRepo(session).briefing_for_delivery(delivery_id)
    if stored is None or stored.delivery_state is not DeliveryState.HELD or ctx.messenger is None:
        return Reply.text("That held briefing was already resolved.")
    result = await deliver(
        ctx.db,
        ctx.messenger,
        delivery_id=delivery_id,
        chat_id=ctx.owner_id,
        chunks=stored.chunks,
        allowed=frozenset({DeliveryState.HELD}),
        clock=lambda: ctx.now,
        final_state=DeliveryState.RESENT,
    )
    if result.state is DeliveryState.RESENT:
        return Reply.text(f"Resent {result.sent_chunks} message(s). The briefing is complete.")
    return Reply.text(
        f"Resend stopped ({esc(result.error_class or 'unknown')}). It is still held; try /held later."
    )


@action("held_dismiss")
async def held_dismiss(ctx: BotContext, payload: dict[str, Any]) -> Reply:
    async with ctx.db.session() as session:
        done = await CycleRepo(session).dismiss_held(int(payload["delivery_id"]), ctx.now)
    return Reply.text(
        "Dismissed. Nothing will be resent." if done else "That held briefing was already resolved."
    )


@command("run", "/run", "Start today's cycle now (it still sends at most once per day)")
async def run(ctx: BotContext, args: list[str]) -> Reply:
    if ctx.dispatcher is None:
        return Reply.text(
            "Workflow dispatch is not configured (GITHUB_DISPATCH_TOKEN, GITHUB_REPOSITORY)."
        )
    await ctx.dispatcher.dispatch("daily.yml", {"trigger": "dispatch"})
    return Reply.text(
        "Started. If today's briefing was already sent, the run exits without sending again."
    )
