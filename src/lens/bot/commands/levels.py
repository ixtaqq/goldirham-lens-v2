"""/level: price levels checked against completed closes in the morning briefing."""

from __future__ import annotations

from lens.bot.commands.ledger import InputError, _number
from lens.bot.router import BotContext, Reply, command
from lens.delivery.format import esc, price, short_day
from lens.domain.alerts import Direction
from lens.storage.levels import LevelAlertRepo
from lens.storage.market import MarketRepo

USAGE = "Usage: /level TICKER above|below PRICE, /level remove ID, or /level to list"


@command(
    "level",
    "/level [TICKER above|below PRICE | remove ID]",
    "Price alerts on completed closes, reported once in the briefing",
)
async def level(ctx: BotContext, args: list[str]) -> Reply:
    if args and args[0].lower() == "remove":
        return await _remove(ctx, args[1:])
    if args:
        return await _add(ctx, args)
    async with ctx.db.session() as session:
        repo = LevelAlertRepo(session)
        active = await repo.active(ctx.owner_id)
        recent = await repo.recent(ctx.owner_id)
        currencies = {
            a.symbol: (await MarketRepo(session).instrument(a.symbol)) for a in [*active, *recent]
        }
    if not active and not recent:
        return Reply.text(f"No price alerts. {USAGE}")

    def currency(symbol: str) -> str:
        found = currencies.get(symbol)
        return found.currency if found else ""

    lines = ["<b>Price alerts</b>"]
    lines += [
        f"• {a.id} {esc(a.symbol)} {a.direction.value} {price(a.level, currency(a.symbol))} "
        f"· set {short_day(a.created_on)}"
        for a in active
    ]
    if recent:
        lines += ["", "<i>Recently reached</i>"]
        lines += [
            f"• {a.id} {esc(a.symbol)} {a.direction.value} {price(a.level, currency(a.symbol))} "
            f"· closed at {price(a.triggered_close, currency(a.symbol))} on {short_day(a.triggered_on)}"
            for a in recent
            if a.triggered_on is not None and a.triggered_close is not None
        ]
    return Reply.text("\n".join(lines))


async def _add(ctx: BotContext, args: list[str]) -> Reply:
    if len(args) != 3 or args[1].lower() not in ("above", "below"):
        return Reply.text(USAGE)
    symbol = args[0].upper()
    try:
        level = _number(args[2], "price")
    except InputError as error:
        return Reply.text(esc(str(error)))
    async with ctx.db.session() as session:
        market = MarketRepo(session)
        ids = await market.instrument_ids([symbol])
        instrument = await market.instrument(symbol)
        if symbol not in ids or instrument is None:
            return Reply.text(
                f"{esc(symbol)} is not known yet. Add it with /watchlist add {esc(symbol)} first."
            )
        direction = Direction(args[1].lower())
        alert_id = await LevelAlertRepo(session).add(
            ctx.owner_id, ids[symbol], direction, level, ctx.settings.owner.today(ctx.now)
        )
    return Reply.text(
        f"Alert {alert_id} set: {esc(symbol)} closing {direction.value} "
        f"{price(level, instrument.currency)}. It is checked against completed closes from the "
        "next session and reported once in the morning briefing."
    )


async def _remove(ctx: BotContext, args: list[str]) -> Reply:
    if len(args) != 1 or not args[0].isdigit():
        return Reply.text("Usage: /level remove ID (the number from /level)")
    alert_id = int(args[0])
    async with ctx.db.session() as session:
        done = await LevelAlertRepo(session).cancel(ctx.owner_id, alert_id, ctx.now)
    return Reply.text(f"Removed alert {alert_id}." if done else f"No active alert {alert_id}.")
