"""/portfolio, /buy, /sell, /fee, /dividend, /split, /journal, /watchlist."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from lens.bot.router import BotContext, Reply, action, command, offer
from lens.delivery.format import esc, money, pct, price, short_day, signed_pct
from lens.domain.holdings import MarkStatus
from lens.domain.instruments import AssetClass, Instrument, UnsupportedMarketError
from lens.domain.money import NonFiniteNumberError, to_decimal
from lens.domain.portfolio import (
    FxRate,
    LedgerError,
    Mark,
    Transaction,
    TxKind,
    build_positions,
    value_portfolio,
)
from lens.storage.ledger import LedgerRepo
from lens.storage.market import MarketRepo

STALE_AFTER = timedelta(days=4)
TX_USAGE = {
    TxKind.BUY: "/buy TICKER QUANTITY PRICE [FEE] [YYYY-MM-DD]",
    TxKind.SELL: "/sell TICKER QUANTITY PRICE [FEE] [YYYY-MM-DD]",
    TxKind.FEE: "/fee TICKER AMOUNT [YYYY-MM-DD]",
    TxKind.DIVIDEND: "/dividend TICKER AMOUNT [YYYY-MM-DD]",
    TxKind.SPLIT: "/split TICKER RATIO [YYYY-MM-DD]  (4 for a 4-for-1 split)",
}


class InputError(ValueError):
    pass


def _number(raw: str, name: str, *, positive: bool = True) -> Decimal:
    try:
        value = to_decimal(raw.replace(",", ""))
    except NonFiniteNumberError as error:
        raise InputError(f"{name} must be a number") from error
    if value < 0 or (positive and value == 0):
        raise InputError(f"{name} must be {'positive' if positive else 'zero or more'}")
    if abs(value) > Decimal("1e12"):
        raise InputError(f"{name} is out of range")
    return value


def _day(raw: str | None, today: date) -> date:
    if raw is None:
        return today
    try:
        value = date.fromisoformat(raw)
    except ValueError as error:
        raise InputError("dates use YYYY-MM-DD") from error
    if value > today or value < date(1990, 1, 1):
        raise InputError("the date must be in the past")
    return value


def _guess_instrument(symbol: str) -> Instrument:
    asset_class = AssetClass.CRYPTO if symbol.endswith("-USD") else AssetClass.STOCK
    return Instrument.create(symbol, asset_class)


def parse_transaction(kind: TxKind, args: list[str], today: date) -> dict[str, Any]:
    """Validate command arguments into a ledger payload. Raises InputError with a plain message."""
    if not args:
        raise InputError(f"Usage: {TX_USAGE[kind]}")
    symbol = args[0].upper()
    if len(symbol) > 24:
        raise InputError("that ticker is too long")
    rest = args[1:]
    payload: dict[str, Any] = {"symbol": symbol, "kind": kind.value}
    if kind in (TxKind.BUY, TxKind.SELL):
        if len(rest) < 2:
            raise InputError(f"Usage: {TX_USAGE[kind]}")
        payload["quantity"] = str(_number(rest[0], "quantity"))
        payload["price"] = str(_number(rest[1], "price"))
        extra = rest[2:]
        fee = Decimal(0)
        if extra and "-" not in extra[0]:
            fee = _number(extra[0], "fee", positive=False)
            extra = extra[1:]
        payload["fee"] = str(fee)
        payload["day"] = _day(extra[0] if extra else None, today).isoformat()
    else:
        if not rest:
            raise InputError(f"Usage: {TX_USAGE[kind]}")
        field = "ratio" if kind is TxKind.SPLIT else "amount"
        payload[field] = str(_number(rest[0], field))
        payload["day"] = _day(rest[1] if len(rest) > 1 else None, today).isoformat()
    return payload


def _describe(payload: dict[str, Any], currency: str) -> str:
    kind = TxKind(payload["kind"])
    day = date.fromisoformat(payload["day"])
    if kind in (TxKind.BUY, TxKind.SELL):
        return (
            f"{kind.value.title()} {payload['quantity']} {esc(payload['symbol'])} at "
            f"{price(Decimal(payload['price']), currency)}, fee {money(Decimal(payload['fee']), currency)}, "
            f"on {short_day(day)} {day.year}"
        )
    if kind is TxKind.SPLIT:
        return f"Split {esc(payload['symbol'])} {payload['ratio']}-for-1 on {short_day(day)} {day.year}"
    amount = money(Decimal(payload["amount"]), currency)
    return (
        f"{kind.value.title()} {amount} for {esc(payload['symbol'])} on {short_day(day)} {day.year}"
    )


async def _propose(ctx: BotContext, kind: TxKind, args: list[str]) -> Reply:
    try:
        payload = parse_transaction(kind, args, ctx.settings.owner.today(ctx.now))
        async with ctx.db.session() as session:
            market = MarketRepo(session)
            instrument = await market.instrument(payload["symbol"]) or _guess_instrument(
                payload["symbol"]
            )
            existing = await LedgerRepo(session).transactions(ctx.owner_id)
        payload["currency"] = instrument.currency
        payload["asset_class"] = instrument.asset_class.value
        trial = [*existing, _as_transaction(payload, 0)]
        build_positions(trial)
    except (InputError, UnsupportedMarketError) as error:
        return Reply.text(esc(str(error)))
    except LedgerError as error:
        return Reply.text(f"Not recorded: {esc(str(error))}")
    buttons = await offer(ctx, "transaction", payload, f"Confirm {kind.value.lower()}")
    return Reply.text(f"Please confirm:\n{_describe(payload, instrument.currency)}", buttons)


def _as_transaction(payload: dict[str, Any], tx_id: int) -> Transaction:
    zero = "0"
    return Transaction(
        tx_id,
        payload["symbol"],
        TxKind(payload["kind"]),
        date.fromisoformat(payload["day"]),
        payload["currency"],
        Decimal(payload.get("quantity", zero)),
        Decimal(payload.get("price", zero)),
        Decimal(payload.get("fee", zero)),
        Decimal(payload.get("amount", zero)),
        Decimal(payload.get("ratio", zero)),
    )


@action("transaction")
async def record_transaction(ctx: BotContext, payload: dict[str, Any]) -> Reply:
    instrument = Instrument.create(payload["symbol"], AssetClass(payload["asset_class"]))
    tx = _as_transaction(payload, 0)
    async with ctx.db.session() as session:
        ids = await MarketRepo(session).ensure_instruments([instrument])
        ledger = LedgerRepo(session)
        try:
            build_positions([*await ledger.transactions(ctx.owner_id), tx])
        except LedgerError as error:
            return Reply.text(f"Not recorded: {esc(str(error))}")
        await ledger.add(
            ctx.owner_id,
            ids[instrument.symbol],
            kind=tx.kind,
            day=tx.day,
            currency=tx.currency,
            quantity=tx.quantity,
            price=tx.price,
            fee=tx.fee,
            amount=tx.amount,
            ratio=tx.ratio,
        )
    return Reply.text(f"Recorded. {_describe(payload, instrument.currency)}.")


for _kind in TX_USAGE:

    def _make(kind: TxKind) -> Any:
        async def handler(ctx: BotContext, args: list[str]) -> Reply:
            return await _propose(ctx, kind, args)

        return handler

    command(
        _kind.value.lower(), TX_USAGE[_kind], f"Record a {_kind.value.lower()} (asks to confirm)"
    )(_make(_kind))


@command("portfolio", "/portfolio", "Holdings with dated marks, MYR totals and exposure")
async def portfolio(ctx: BotContext, args: list[str]) -> Reply:
    base = ctx.settings.owner.base_currency
    today = ctx.settings.owner.today(ctx.now)
    async with ctx.db.session() as session:
        transactions = await LedgerRepo(session).transactions(ctx.owner_id)
        positions = {s: p for s, p in build_positions(transactions).items() if p.quantity > 0}
        if not positions:
            return Reply.text("No open positions. Record one with /buy.")
        market = MarketRepo(session)
        instruments = await market.instruments_by_symbol(positions)
        bars = await market.load_bars(positions, since=today - timedelta(days=30))
        fx: dict[str, FxRate] = {}
        for currency in {p.currency for p in positions.values()} - {base}:
            rate = await market.latest_fx(currency, base, today)
            if rate is not None:
                fx[currency] = rate
    marks: dict[str, Mark] = {}
    for symbol in positions:
        usable = [b for b in bars.get(symbol, []) if b.usable]
        if not usable:
            marks[symbol] = Mark(None, None, None, MarkStatus.UNAVAILABLE)
            continue
        last = usable[-1]
        status = MarkStatus.STALE if today - last.day > STALE_AFTER else MarkStatus.FRESH
        marks[symbol] = Mark(last.close, last.day, last.provider, status)
    snapshot = value_portfolio(
        positions,
        asset_classes={s: i.asset_class for s, i in instruments.items()},
        marks=marks,
        fx=fx,
        base_currency=base,
    )
    lines = [f"<b>Portfolio</b> · {money(snapshot.total_base, base)}"]
    for h in snapshot.holdings:
        mark = (
            f"{price(h.mark.price, h.currency)} ({short_day(h.mark.day)})"
            if h.mark.price is not None and h.mark.day is not None
            else "no verified price"
        )
        stale = " · stale" if h.mark.status is MarkStatus.STALE else ""
        pnl = f" · {signed_pct(h.unrealized_pct)}" if h.unrealized_pct is not None else ""
        weight = f" · {pct(h.weight_pct)}" if h.weight_pct is not None else ""
        lines.append(f"• {esc(h.symbol)} {h.quantity.normalize():f} @ {mark}{stale}{pnl}{weight}")
    if snapshot.excluded_from_total:
        lines.append(
            "Not in total (no price or FX rate): "
            + ", ".join(esc(s) for s in snapshot.excluded_from_total)
        )
    if snapshot.fx_days:
        lines.append("FX dated " + ", ".join(short_day(d) for d in snapshot.fx_days))
    if snapshot.exposure_by_currency:
        lines.append(
            "By currency: "
            + " · ".join(
                f"{esc(k)} {pct(v)}" for k, v in sorted(snapshot.exposure_by_currency.items())
            )
        )
    return Reply.text("\n".join(lines))


@command(
    "journal", "/journal [note TICKER text]", "Recent transactions, closed lots, and thesis notes"
)
async def journal(ctx: BotContext, args: list[str]) -> Reply:
    if len(args) >= 3 and args[0].lower() == "note":
        symbol, text = args[1].upper(), " ".join(args[2:])[:1000]
        async with ctx.db.session() as session:
            ids = await MarketRepo(session).instrument_ids([symbol])
            if symbol not in ids:
                return Reply.text(f"{esc(symbol)} is not known yet.")
            await LedgerRepo(session).set_note(ctx.owner_id, ids[symbol], text)
        return Reply.text(
            f"Saved your note for {esc(symbol)}. It stays private and is never sent to AI."
        )
    async with ctx.db.session() as session:
        ledger = LedgerRepo(session)
        transactions = await ledger.transactions(ctx.owner_id)
        notes = await ledger.notes(ctx.owner_id)
    if not transactions:
        return Reply.text("The journal is empty. Record a trade with /buy.")
    positions = build_positions(transactions)
    lines = ["<b>Recent transactions</b>"]
    for t in transactions[-12:]:
        detail = (
            f"{t.quantity.normalize():f} @ {price(t.price, t.currency)}"
            if t.kind in (TxKind.BUY, TxKind.SELL)
            else (
                f"{t.ratio.normalize():f}-for-1"
                if t.kind is TxKind.SPLIT
                else money(t.amount, t.currency)
            )
        )
        lines.append(f"• {t.day.isoformat()} {t.kind.value} {esc(t.symbol)} {detail}")
    closed = [c for p in positions.values() for c in p.closed]
    if closed:
        lines += ["", "<b>Closed lots</b>"]
        for c in closed[-8:]:
            currency = positions[c.symbol].currency
            lines.append(
                f"• {esc(c.symbol)} {c.quantity.normalize():f} · {c.opened.isoformat()} to {c.closed.isoformat()} · "
                f"{money(c.realized, currency)}"
            )
    if notes:
        lines += ["", "<b>Notes</b>"] + [f"• {esc(s)}: {esc(n)}" for s, n in sorted(notes.items())]
    return Reply.text("\n".join(lines))


@command(
    "watchlist",
    "/watchlist [add TICKER [crypto|stock|etf] | remove TICKER]",
    "View or change the watchlist",
)
async def watchlist(ctx: BotContext, args: list[str]) -> Reply:
    async with ctx.db.session() as session:
        market = MarketRepo(session)
        if len(args) >= 2 and args[0].lower() in ("add", "remove"):
            symbol = args[1].upper()
            if args[0].lower() == "remove":
                existing = await market.instrument(symbol)
                if existing is None:
                    return Reply.text(f"{esc(symbol)} is not on the watchlist.")
                await market.set_watched(ctx.owner_id, existing, False)
                return Reply.text(f"Removed {esc(symbol)}. Held positions keep receiving prices.")
            asset_class = (
                AssetClass(args[2].lower())
                if len(args) > 2 and args[2].lower() in AssetClass._value2member_map_
                else None
            )
            try:
                instrument = Instrument.create(
                    symbol, asset_class or _guess_instrument(symbol).asset_class
                )
            except UnsupportedMarketError:
                return Reply.text(
                    f"{esc(symbol)} is not on a supported market (US, Bursa .KL, or crypto -USD)."
                )
            await market.set_watched(ctx.owner_id, instrument, True)
        watched = await market.watchlist(ctx.owner_id)
    if len(args) >= 2 and args[0].lower() == "add":
        started = ""
        if ctx.dispatcher is not None:
            await ctx.dispatcher.dispatch("backfill.yml", {"symbol": instrument.symbol})
            started = " Backfill started; a message follows when it finishes."
        return Reply.text(
            f"Added {esc(instrument.symbol)} ({instrument.asset_class.value}).{started}"
        )
    lines = ["<b>Watchlist</b>"] + [
        f"• {esc(i.symbol)} · {esc(i.name)} · {i.asset_class.value}" for i in watched
    ]
    return Reply.text("\n".join(lines))
