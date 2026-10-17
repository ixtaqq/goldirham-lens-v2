"""/preferences, /alerts, /feedback, /privacy, /help, /start."""

from __future__ import annotations

import re
from datetime import time
from decimal import Decimal

from lens.bot.router import COMMANDS, BotContext, Reply, command
from lens.delivery.format import esc
from lens.domain.money import NonFiniteNumberError, to_decimal
from lens.storage.cycles import CycleRepo
from lens.storage.ops import OpsRepo

_HOURS = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


@command(
    "preferences",
    "/preferences [risk PCT | detail concise|detailed]",
    "Risk per setup and briefing detail",
)
async def preferences(ctx: BotContext, args: list[str]) -> Reply:
    if len(args) >= 2 and args[0].lower() == "risk":
        try:
            value = to_decimal(args[1].rstrip("%"))
        except NonFiniteNumberError:
            return Reply.text("Risk must be a number, for example /preferences risk 0.75")
        if not Decimal("0.1") <= value <= Decimal(5):
            return Reply.text("Risk per setup must be between 0.1% and 5%.")
        async with ctx.db.session() as session:
            await OpsRepo(session).set_preference(ctx.owner_id, risk_per_trade_pct=value)
        return Reply.text(f"Risk per setup is now {value}%. Tomorrow's setups use it.")
    if (
        len(args) >= 2
        and args[0].lower() == "detail"
        and args[1].lower() in ("concise", "detailed")
    ):
        async with ctx.db.session() as session:
            await OpsRepo(session).set_preference(ctx.owner_id, detail=args[1].lower())
        return Reply.text(f"Briefings will be {args[1].lower()}.")
    async with ctx.db.session() as session:
        prefs = await OpsRepo(session).preferences(ctx.owner_id)
    risk = prefs.risk_per_trade_pct or ctx.settings.risk.risk_per_trade_pct
    detail = prefs.detail or ctx.settings.owner.detail
    return Reply.text(
        f"<b>Preferences</b>\nRisk per setup: {risk}%\nDetail: {esc(detail)}\n"
        f"Alerts: {esc(prefs.alerts_mode or ctx.settings.alerts.mode)}\n"
        "Change with /preferences risk 0.75 or /preferences detail detailed"
    )


@command(
    "alerts",
    "/alerts [digest|immediate|quiet HH:MM-HH:MM]",
    "How close-based holding alerts reach you",
)
async def alerts(ctx: BotContext, args: list[str]) -> Reply:
    if args and args[0].lower() in ("digest", "immediate"):
        async with ctx.db.session() as session:
            await OpsRepo(session).set_preference(ctx.owner_id, alerts_mode=args[0].lower())
        return Reply.text(
            "Alerts arrive in the morning briefing."
            if args[0].lower() == "digest"
            else "Alerts arrive after each market close, outside quiet hours."
        )
    if len(args) >= 2 and args[0].lower() == "quiet":
        match = _HOURS.match(args[1])
        if not match:
            return Reply.text("Use /alerts quiet 23:00-07:00")
        start, end = time(int(match[1]), int(match[2])), time(int(match[3]), int(match[4]))
        return Reply.text(
            f"Quiet hours {start:%H:%M} to {end:%H:%M} noted. Set them in settings.yaml to make them permanent."
        )
    quiet = ctx.settings.alerts.quiet_hours
    return Reply.text(
        f"Alerts: {esc(ctx.settings.alerts.mode)} · quiet {quiet[0]:%H:%M}-{quiet[1]:%H:%M}\n"
        "Use /alerts digest or /alerts immediate"
    )


@command("feedback", "/feedback useful|quiet|noisy [note]", "Rate the latest briefing")
async def feedback(ctx: BotContext, args: list[str]) -> Reply:
    if not args or args[0].lower() not in ("useful", "quiet", "noisy"):
        return Reply.text(
            "Use /feedback useful, /feedback quiet or /feedback noisy, optionally with a note."
        )
    async with ctx.db.session() as session:
        latest = await CycleRepo(session).latest_briefing(ctx.owner_id)
        if latest is None:
            return Reply.text("There is no briefing to rate yet.")
        await OpsRepo(session).save_feedback(
            ctx.owner_id, latest.id, args[0].lower(), " ".join(args[1:])[:500] or None
        )
    return Reply.text(
        f"Thanks. Recorded '{esc(args[0].lower())}' for {latest.briefing_date.isoformat()}."
    )


PRIVACY = (
    "<b>Privacy</b>\n"
    "• Your ledger, notes and briefings live in your own PostgreSQL database.\n"
    "• Market data comes from public providers; no personal data is sent to them.\n"
    "• Commands work only from your Telegram account, in this private chat.\n"
    "• AI narrative is off by default. When enabled, only the fact catalog is sent: market closes and changes, "
    "setup levels, and holding percentages. Quantities, entry prices, account values and notes are excluded "
    "unless you opt in.\n"
    "• Nothing here places trades or connects to a broker."
)


@command("privacy", "/privacy", "What data is stored and what ever leaves the server")
async def privacy(ctx: BotContext, args: list[str]) -> Reply:
    return Reply.text(PRIVACY)


@command("help", "/help", "Every command")
async def help_command(ctx: BotContext, args: list[str]) -> Reply:
    lines = ["<b>Commands</b>"] + [
        f"{esc(c.usage)} · {esc(c.summary)}"
        for c in sorted(COMMANDS.values(), key=lambda c: c.name)
    ]
    return Reply.text("\n".join(lines))


@command("start", "/start", "Welcome")
async def start(ctx: BotContext, args: list[str]) -> Reply:
    return Reply.text(
        "Goldirham Lens is connected. Your briefing arrives every morning before 08:00 Malaysia time.\n"
        "Try /today, /why SPY, /portfolio or /help."
    )
