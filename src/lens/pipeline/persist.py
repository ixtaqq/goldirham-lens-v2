"""Write one cycle's results. Every write is an upsert keyed by its natural identity."""

from __future__ import annotations

from lens.data.collect import AssetData
from lens.data.providers.base import CallLog
from lens.pipeline.analysis import Analysis
from lens.pipeline.inputs import CycleInputs
from lens.storage.cycles import CycleRepo
from lens.storage.db import Database
from lens.storage.levels import LevelAlertRepo
from lens.storage.market import MarketRepo
from lens.storage.signals import SignalRepo


async def persist_market(db: Database, data: dict[str, AssetData]) -> int:
    revisions = 0
    async with db.session() as session:
        market = MarketRepo(session)
        ids = await market.ensure_instruments(item.instrument for item in data.values())
        for symbol, item in data.items():
            revisions += await market.upsert_bars(ids[symbol], item.bars)
            await market.record_splits(ids[symbol], item.splits, item.primary)
    return revisions


async def persist_analysis(
    db: Database, inputs: CycleInputs, analysis: Analysis, run_id: int | None
) -> int:
    """Store decisions, open new signals for live setups, advance open signals, store reviews."""
    created = 0
    async with db.session() as session:
        market = MarketRepo(session)
        signals = SignalRepo(session)
        ids = await market.instrument_ids(analysis.assets)
        expiry = {s.version: s.params.expiry_days for s in analysis.strategies}
        for symbol, item in analysis.assets.items():
            for decision in item.decisions:
                await signals.save_decision(
                    inputs.owner_id, ids[symbol], decision, item.asset.readiness, run_id
                )
        for decision in analysis.setups:
            if await signals.create_signal(
                inputs.owner_id, ids[decision.symbol], decision, expiry[decision.strategy_version]
            ):
                created += 1
        for update in analysis.signal_updates:
            await signals.apply_state(update.signal.id, update.state, list(update.events))
        alerts = LevelAlertRepo(session)
        for hit in analysis.alert_hits:
            await alerts.mark_triggered(hit.alert.id, hit.day, hit.close)
        for symbol, review in analysis.reviews.items():
            if symbol in ids:
                await signals.save_review(
                    inputs.owner_id, ids[symbol], inputs.briefing_date, review
                )
    return created


async def persist_calls(db: Database, run_id: int | None, log: CallLog) -> None:
    async with db.session() as session:
        await CycleRepo(session).record_provider_calls(
            run_id, [(c.provider, c.ok, c.latency_ms, c.error_class) for c in log.calls]
        )
