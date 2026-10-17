"""/today, /briefing, /why, /readiness, /scorecard, /strategy."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from lens.bot.router import BotContext, Reply, command
from lens.delivery.chunker import chunk
from lens.delivery.format import esc, price, short_day
from lens.delivery.renderer import render_sections
from lens.domain.briefing import BriefingDocument
from lens.domain.reasons import LABELS, PASS_CODES, ReasonCode
from lens.domain.scorecard import DEFINITIONS, ExitModel, build_scorecard
from lens.storage.cycles import CycleRepo, StoredBriefing
from lens.storage.signals import SignalRepo
from lens.storage.strategies import StrategyRepo

INDICATOR_LABELS = (
    ("close", "Close"),
    ("sma50", "50-day average"),
    ("sma200", "200-day average"),
    ("rsi14", "RSI 14"),
    ("atr14", "ATR 14"),
    ("swing_low", "Recent swing low"),
    ("high_52w", "52-week high"),
)


def _rendered(stored: StoredBriefing) -> list[str]:
    return chunk(render_sections(BriefingDocument.model_validate(stored.document)))


@command("today", "/today", "The latest briefing, re-rendered from storage")
async def today(ctx: BotContext, args: list[str]) -> Reply:
    async with ctx.db.session() as session:
        stored = await CycleRepo(session).latest_briefing(ctx.owner_id)
    if stored is None:
        return Reply.text(
            "No briefing has been stored yet. The first one arrives after the next scheduled run."
        )
    return Reply(_rendered(stored))


@command("briefing", "/briefing YYYY-MM-DD", "A saved briefing for a date")
async def briefing(ctx: BotContext, args: list[str]) -> Reply:
    try:
        day = date.fromisoformat(args[0]) if args else None
    except ValueError:
        day = None
    async with ctx.db.session() as session:
        repo = CycleRepo(session)
        if day is None:
            recent = await repo.recent_briefings(ctx.owner_id)
            if not recent:
                return Reply.text("No briefings stored yet.")
            lines = ["<b>Recent briefings</b> (use /briefing YYYY-MM-DD)"]
            lines += [
                f"• {d.isoformat()} · {esc(mode)} · {esc((state or 'not delivered').lower())}"
                for d, mode, state in recent
            ]
            return Reply.text("\n".join(lines))
        stored = await repo.briefing_on(ctx.owner_id, day)
    if stored is None:
        return Reply.text(f"No briefing stored for {day.isoformat()}.")
    return Reply(_rendered(stored))


def _indicator(value: Any, currency: str, key: str) -> str:
    if value is None:
        return "n/a"
    if key in ("rsi14",):
        return f"{float(value):.1f}"
    return price(Decimal(str(value)), currency) if key != "atr14" else f"{float(value):,.4g}"


@command("why", "/why TICKER", "The full reasoning behind today's decision on one asset")
async def why(ctx: BotContext, args: list[str]) -> Reply:
    if not args:
        return Reply.text("Usage: /why TICKER, for example /why SPY")
    symbol = args[0].upper()
    async with ctx.db.session() as session:
        decisions = await SignalRepo(session).latest_decisions(ctx.owner_id, symbol)
    if not decisions:
        return Reply.text(
            f"No stored decision for {esc(symbol)} yet. It may not be on the watchlist."
        )
    first = decisions[0]
    currency = "MYR" if symbol.endswith(".KL") else "USD"
    lines = [f"<b>{esc(symbol)}</b> · session {short_day(first.session)}"]
    if first.readiness:
        lines.append("Readiness: " + "; ".join(LABELS[r] for r in first.readiness))
    else:
        lines.append("Readiness: ready (200 verified sessions, latest session present)")
    lines.append("")
    lines += [
        f"{label}: {_indicator(first.indicators.get(key), currency, key)}"
        for key, label in INDICATOR_LABELS
    ]
    for decision in decisions:
        lines += ["", f"<b>{esc(decision.strategy)}</b> {esc(decision.strategy_version)}"]
        if decision.readiness:
            lines.append("Not evaluated: the data is not ready.")
            continue
        for reason in decision.reasons:
            mark = "✓" if reason in PASS_CODES else "✗"
            lines.append(f"{mark} {esc(LABELS[reason])}")
        if decision.setup:
            s = decision.setup
            lines.append(
                f"Setup: entry {price(Decimal(s['entry']), currency)}, stop {price(Decimal(s['stop']), currency)}, "
                f"T1 {price(Decimal(s['t1']), currency)}, T2 {price(Decimal(s['t2']), currency)}, size {s['size_pct']}%"
            )
            if ReasonCode.ASSET_CLASS_CAP_REACHED in decision.reasons:
                lines.append("Held back: the asset-class exposure cap is reached.")
    return Reply.text("\n".join(lines))


@command(
    "readiness", "/readiness [TICKER]", "Which assets have enough verified history, and why not"
)
async def readiness(ctx: BotContext, args: list[str]) -> Reply:
    async with ctx.db.session() as session:
        from lens.storage.market import MarketRepo

        watched = await MarketRepo(session).watchlist(ctx.owner_id)
        symbols = [i.symbol for i in watched if not args or i.symbol == args[0].upper()]
        rows = {s: await SignalRepo(session).latest_decisions(ctx.owner_id, s) for s in symbols}
    if not rows:
        return Reply.text(
            "That asset is not on the watchlist." if args else "The watchlist is empty."
        )
    lines = ["<b>Readiness</b>"]
    for symbol, decisions in rows.items():
        if not decisions:
            lines.append(f"• {esc(symbol)}: not evaluated yet")
            continue
        reasons = decisions[0].readiness
        status = "ready" if not reasons else "; ".join(LABELS[r] for r in reasons)
        lines.append(f"• {esc(symbol)} ({short_day(decisions[0].session)}): {esc(status)}")
    return Reply.text("\n".join(lines))


@command("scorecard", "/scorecard", "Signal outcomes with their definitions")
async def scorecard(ctx: BotContext, args: list[str]) -> Reply:
    async with ctx.db.session() as session:
        records = await SignalRepo(session).records(ctx.owner_id)
    settings = ctx.settings.scorecard
    card = build_scorecard(
        records,
        as_of=ctx.now.date(),
        window_days=settings.window_days,
        min_sample=settings.min_sample,
        exit_model=ExitModel(settings.exit_model),
    )
    lines = [
        f"<b>Scorecard</b> · last {settings.window_days} days · exit model {card.exit_model.value}",
        f"Resolved {card.resolved} · open {card.open} · unverifiable {card.unverifiable}",
    ]
    if not card.sufficient:
        lines.append(
            f"Fewer than {settings.min_sample} resolved signals, so no rates are shown yet."
        )
    else:
        lines += [
            f"Expectancy {card.expectancy}R (90% interval {card.ci_low}R to {card.ci_high}R)",
            f"Win rate {card.win_rate}% · T1 touched {card.t1_touch_rate}% · median hold {card.median_hold_days} days",
        ]
    lines += ["", "<i>Definitions</i>"] + [f"• {esc(k)}: {esc(v)}" for k, v in DEFINITIONS.items()]
    return Reply.text("\n".join(lines))


@command("strategy", "/strategy", "Strategy versions, whether each is live, and its backtest")
async def strategy(ctx: BotContext, args: list[str]) -> Reply:
    async with ctx.db.session() as session:
        repo = StrategyRepo(session)
        versions = await repo.versions()
        reports = {v.version: await repo.latest_report(v.version) for v in versions}
    if not versions:
        return Reply.text("No strategy versions recorded yet.")
    lines = ["<b>Strategies</b>"]
    for v in versions:
        state = "LIVE" if v.activated_at else "not live"
        lines.append(f"• {esc(v.name)} {esc(v.version)}: {state}")
        report = reports.get(v.version)
        if report is not None:
            summary = report.report.get("full_to_t2", {}).get("out_of_sample", {})
            if summary.get("resolved"):
                lines.append(
                    f"   out of sample: {summary['resolved']} trades, expectancy {summary['expectancy_r']}R "
                    f"({summary['expectancy_ci90_r'][0]}R to {summary['expectancy_ci90_r'][1]}R)"
                )
            baseline = report.report.get("random_entry_baseline")
            if baseline:
                lines.append(f"   random entries: {baseline['mean_expectancy_r']}R")
        else:
            lines.append("   no backtest report yet")
    return Reply.text("\n".join(lines))
