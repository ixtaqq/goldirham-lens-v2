"""Everything analysis and compose read, as one JSON-safe snapshot. Replay starts from this."""

from __future__ import annotations

import base64
import gzip
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from lens.domain.bars import Bar, BarQuality
from lens.domain.briefing import Headline
from lens.domain.evaluation import Levels, SignalState, SignalStatus
from lens.domain.holdings import ReviewAction
from lens.domain.instruments import AssetClass, Instrument, Market
from lens.domain.portfolio import FxRate, Transaction, TxKind
from lens.domain.reasons import ReasonCode
from lens.domain.strategy.base import Fundamentals

INPUTS_VERSION = 1


class _In(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BarIn(_In):
    day: date
    o: Decimal
    h: Decimal
    lo: Decimal
    c: Decimal
    v: Decimal
    provider: str
    quality: BarQuality
    reasons: tuple[ReasonCode, ...] = ()

    @classmethod
    def of(cls, bar: Bar) -> BarIn:
        return cls(
            day=bar.day,
            o=bar.open,
            h=bar.high,
            lo=bar.low,
            c=bar.close,
            v=bar.volume,
            provider=bar.provider,
            quality=bar.quality,
            reasons=bar.reasons,
        )

    def bar(self, symbol: str) -> Bar:
        return Bar(
            symbol,
            self.day,
            self.o,
            self.h,
            self.lo,
            self.c,
            self.v,
            self.provider,
            self.quality,
            self.reasons,
        )


class AssetIn(_In):
    symbol: str
    name: str
    asset_class: AssetClass
    market: Market
    currency: str
    watched: bool
    closed_sessions: tuple[date, ...]
    bars: tuple[BarIn, ...]
    readiness: tuple[ReasonCode, ...]
    primary: str
    cross_check: str | None
    errors: tuple[str, ...] = ()

    def instrument(self) -> Instrument:
        return Instrument(self.symbol, self.name, self.asset_class, self.market, self.currency)

    def domain_bars(self) -> list[Bar]:
        return [b.bar(self.symbol) for b in self.bars]


class SignalIn(_In):
    id: int
    symbol: str
    strategy: str
    signal_day: date
    expiry_days: int
    entry: Decimal
    stop: Decimal
    t1: Decimal
    t2: Decimal
    status: SignalStatus
    last_evaluated: date | None
    t1_touched_on: date | None
    mfe_r: Decimal
    mae_r: Decimal
    last_close: Decimal | None

    def levels(self) -> Levels:
        return Levels(self.entry, self.stop, self.t1, self.t2)

    def state(self) -> SignalState:
        return SignalState(
            self.status,
            self.last_evaluated,
            self.t1_touched_on,
            None,
            None,
            None,
            None,
            self.mfe_r,
            self.mae_r,
            self.last_close,
        )


class TxIn(_In):
    id: int
    symbol: str
    kind: TxKind
    day: date
    currency: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    amount: Decimal
    ratio: Decimal

    def transaction(self) -> Transaction:
        return Transaction(
            self.id,
            self.symbol,
            self.kind,
            self.day,
            self.currency,
            self.quantity,
            self.price,
            self.fee,
            self.amount,
            self.ratio,
        )


class FxIn(_In):
    quote: str
    base: str
    rate: Decimal
    day: date
    source: str

    def fx(self) -> FxRate:
        return FxRate(self.quote, self.base, self.rate, self.day, self.source)


class FundamentalsIn(_In):
    symbol: str
    pe_ratio: Decimal | None
    revenue_growth_pct: Decimal | None
    as_of: date

    def fundamentals(self) -> Fundamentals:
        return Fundamentals(self.pe_ratio, self.revenue_growth_pct, self.as_of)


class PreviousIn(_In):
    briefing_date: date
    setup_symbols: tuple[str, ...]


class ContextIn(_In):
    fear_greed: int | None = None
    fear_greed_label: str | None = None
    headlines: tuple[Headline, ...] = ()


class NarrativeIn(_In):
    paragraphs: tuple[str, ...]
    model: str


class CycleInputs(_In):
    version: int = INPUTS_VERSION
    briefing_date: date
    generated_at: datetime
    cycle_id: str
    trigger: str
    mode: Literal["deterministic", "degraded"]
    degraded_reason: str | None
    late: bool
    owner_id: int
    base_currency: str
    detail: Literal["concise", "detailed"]
    risk_per_trade_pct: Decimal
    settings: dict[str, Any]
    active_versions: tuple[str, ...]
    assets: tuple[AssetIn, ...]
    signals: tuple[SignalIn, ...]
    transactions: tuple[TxIn, ...]
    fx: tuple[FxIn, ...]
    fundamentals: tuple[FundamentalsIn, ...]
    previous: PreviousIn | None
    previous_reviews: dict[str, ReviewAction]
    context: ContextIn
    sources_unavailable: tuple[str, ...]
    narrative: NarrativeIn | None = None

    def asset(self, symbol: str) -> AssetIn | None:
        return next((a for a in self.assets if a.symbol == symbol), None)


def pack(inputs: CycleInputs) -> dict[str, Any]:
    raw = inputs.model_dump_json().encode()
    return {"version": inputs.version, "gz": base64.b64encode(gzip.compress(raw, mtime=0)).decode()}


def unpack(stored: dict[str, Any]) -> CycleInputs:
    if stored.get("version") != INPUTS_VERSION:
        raise ValueError(f"unsupported inputs version {stored.get('version')}")
    return CycleInputs.model_validate(json.loads(gzip.decompress(base64.b64decode(stored["gz"]))))
