"""Backfill one asset and close-based holding alerts. Both message the owner when they finish."""

from __future__ import annotations

from datetime import datetime

from lens.data.collect import Collector, provider_factories
from lens.delivery.format import esc
from lens.delivery.telegram import TelegramClient
from lens.domain.holdings import HoldingRules, MarkStatus, ReviewAction, review_holding
from lens.domain.instruments import Instrument
from lens.domain.market_view import MarketView
from lens.domain.portfolio import build_positions
from lens.domain.reasons import LABELS
from lens.settings import Secrets, Settings
from lens.storage.db import Database
from lens.storage.ledger import LedgerRepo
from lens.storage.market import MarketRepo
from lens.storage.ops import OpsRepo


def _collector(settings: Settings, secrets: Secrets, now: datetime) -> Collector:
    key = (
        secrets.alpha_vantage_api_key.get_secret_value() if secrets.alpha_vantage_api_key else None
    )
    return Collector(settings, now, factories=provider_factories(key))


async def backfill(settings: Settings, secrets: Secrets, symbol: str, now: datetime) -> str:
    db = Database(secrets.require("database_url_direct"))
    try:
        async with db.session() as session:
            instrument: Instrument | None = await MarketRepo(session).instrument(symbol.upper())
        if instrument is None:
            return f"{symbol} is not known; add it with /watchlist add first."
        data = (await _collector(settings, secrets, now).collect_all([instrument]))[
            instrument.symbol
        ]
        async with db.session() as session:
            market = MarketRepo(session)
            ids = await market.ensure_instruments([instrument])
            await market.upsert_bars(ids[instrument.symbol], data.bars)
            await market.record_splits(ids[instrument.symbol], data.splits, data.primary)
        readiness = data.readiness
        status = "ready" if readiness.ready else "; ".join(LABELS[r] for r in readiness.reasons)
        return (
            f"Backfill finished for {esc(instrument.symbol)}: {readiness.verified_sessions}/"
            f"{readiness.required_sessions} verified sessions, {esc(status)}."
        )
    finally:
        await db.dispose()


async def holding_alerts(settings: Settings, secrets: Secrets, now: datetime) -> list[str]:
    """One message per new EXIT or REDUCE episode, deduplicated per asset and session."""
    owner = secrets.owner_id()
    db = Database(secrets.require("database_url_direct"))
    try:
        async with db.session() as session:
            transactions = await LedgerRepo(session).transactions(owner)
            prefs = await OpsRepo(session).preferences(owner)
        if (prefs.alerts_mode or settings.alerts.mode) != "immediate":
            return []
        positions = {s: p for s, p in build_positions(transactions).items() if p.quantity > 0}
        if not positions:
            return []
        async with db.session() as session:
            market = MarketRepo(session)
            instruments = await market.instruments_by_symbol(positions)
            ids = await market.instrument_ids(positions)
        data = await _collector(settings, secrets, now).collect_all(list(instruments.values()))
        rules = HoldingRules(
            settings.holdings.chandelier_atr_multiple,
            settings.holdings.exit_below_ma200_sessions,
            settings.holdings.drawdown_review_pct,
            settings.risk.max_position_pct,
        )
        messages = []
        for symbol, position in positions.items():
            item = data.get(symbol)
            if item is None or position.first_opened is None:
                continue
            usable = [b for b in item.bars if b.usable]
            if not usable:
                continue
            view = MarketView.of(symbol, usable, as_of=usable[-1].day)
            review = review_holding(
                view,
                entry_day=position.first_opened,
                weight_pct=None,
                mark_status=MarkStatus.FRESH,
                rules=rules,
            )
            if review.action not in (ReviewAction.EXIT, ReviewAction.REDUCE):
                continue
            async with db.session() as session:
                first = await OpsRepo(session).claim_alert(
                    owner, ids[symbol], review.action.value, usable[-1].day
                )
            if first:
                why = "; ".join(LABELS[r] for r in review.reasons)
                messages.append(
                    f"<b>{review.action.value}</b> review for {esc(symbol)} after the "
                    f"{usable[-1].day.isoformat()} close: {esc(why)}. Research only, not advice."
                )
        if messages:
            telegram = TelegramClient(secrets.require("telegram_bot_token"))
            try:
                for text in messages:
                    await telegram.send_message(owner, text)
            finally:
                await telegram.close()
        return messages
    finally:
        await db.dispose()
