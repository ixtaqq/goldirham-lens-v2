"""Synthetic, deterministic cycle inputs for pipeline tests and the showcase demo."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from lens.data.collect import AssetData
from lens.domain.bars import Bar, BarQuality
from lens.domain.briefing import Headline
from lens.domain.instruments import AssetClass, Instrument
from lens.domain.portfolio import TxKind
from lens.domain.readiness import Readiness
from lens.domain.reasons import ReasonCode
from lens.pipeline.inputs import AssetIn, BarIn, ContextIn, CycleInputs, TxIn
from lens.settings import load_settings
from tests.helpers import business_days, make_bars, uptrend_then_pullback

BRIEFING_DAY = date(2026, 10, 16)
GENERATED = datetime(2026, 10, 15, 23, 1, tzinfo=UTC)


def calendar_days(count: int, end: date = date(2026, 10, 15)) -> list[date]:
    days = business_days(date(2025, 1, 1), 600)
    days = [d for d in days if d <= end]
    return days[-count:]


def asset(
    symbol: str,
    asset_class: AssetClass,
    closes: Sequence[float],
    *,
    name: str | None = None,
    watched: bool = True,
    readiness: tuple[ReasonCode, ...] = (),
    last_quality: BarQuality | None = None,
    spread: str = "0.004",
) -> AssetIn:
    instrument = Instrument.create(symbol, asset_class, name)
    days = calendar_days(len(closes))
    bars = make_bars(symbol, closes, days=days, spread=spread)
    if last_quality is not None:
        bars[-1] = bars[-1].with_quality(last_quality)
    return AssetIn(
        symbol=symbol,
        name=instrument.name,
        asset_class=asset_class,
        market=instrument.market,
        currency=instrument.currency,
        watched=watched,
        closed_sessions=tuple(days),
        bars=tuple(BarIn.of(b) for b in bars),
        readiness=readiness,
        primary="test",
        cross_check="test2",
    )


def standard_assets() -> list[AssetIn]:
    rising = [100.0 * 1.002**i for i in range(260)]
    return [
        asset("SPY", AssetClass.ETF, [500 * 1.001**i for i in range(260)], name="SPDR S&P 500 ETF"),
        asset("QQQ", AssetClass.ETF, uptrend_then_pullback(), name="Invesco QQQ"),
        asset("AAPL", AssetClass.STOCK, rising, name="Apple"),
        asset("1155.KL", AssetClass.STOCK, [9.0 * 1.0005**i for i in range(260)], name="Maybank"),
        asset("BTC-USD", AssetClass.CRYPTO, [60000 * 1.001**i for i in range(260)], name="Bitcoin"),
        asset(
            "NVDA",
            AssetClass.STOCK,
            rising[:120],
            name="NVIDIA",
            readiness=(ReasonCode.INSUFFICIENT_HISTORY,),
        ),
    ]


def tx(
    id_: int,
    symbol: str,
    kind: str,
    day: str,
    currency: str,
    *,
    quantity: str = "0",
    price: str = "0",
    fee: str = "0",
    amount: str = "0",
    ratio: str = "0",
) -> TxIn:
    return TxIn(
        id=id_,
        symbol=symbol,
        kind=TxKind(kind),
        day=date.fromisoformat(day),
        currency=currency,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal(fee),
        amount=Decimal(amount),
        ratio=Decimal(ratio),
    )


def make_inputs(**overrides: Any) -> CycleInputs:
    settings = load_settings()
    values: dict[str, Any] = {
        "briefing_date": BRIEFING_DAY,
        "generated_at": GENERATED,
        "cycle_id": "3f2a9c1e-0000-4000-8000-000000000000",
        "trigger": "schedule_1",
        "mode": "deterministic",
        "degraded_reason": None,
        "late": False,
        "owner_id": 42,
        "base_currency": "MYR",
        "detail": "concise",
        "risk_per_trade_pct": Decimal("1.0"),
        "settings": settings.model_dump(mode="json"),
        "active_versions": (),
        "assets": tuple(standard_assets()),
        "signals": (),
        "transactions": (),
        "fx": (),
        "fundamentals": (),
        "previous": None,
        "previous_reviews": {},
        "context": ContextIn(
            fear_greed=63,
            fear_greed_label="Greed",
            headlines=(
                Headline(title="Markets steady ahead of rate decision", source="Demo Wire"),
            ),
        ),
        "sources_unavailable": (),
    }
    values.update(overrides)
    return CycleInputs(**values)


def active_pullback_version() -> str:
    from lens.pipeline.analysis import strategies_from

    return next(
        s.version for s in strategies_from(load_settings()) if s.name == "pullback_in_uptrend"
    )


def asset_data_from(inputs: CycleInputs) -> dict[str, AssetData]:
    """Turn input assets back into collector output, for a fake collector."""
    result = {}
    for a in inputs.assets:
        bars = tuple(b.bar(a.symbol) for b in a.bars)
        readiness = Readiness(a.readiness, bars[-1].day if bars else None, len(bars), 200)
        result[a.symbol] = AssetData(
            a.instrument(), bars, a.closed_sessions, readiness, a.primary, a.cross_check
        )
    return result


def bars_of(inputs: CycleInputs, symbol: str) -> list[Bar]:
    found = inputs.asset(symbol)
    assert found is not None
    return found.domain_bars()
