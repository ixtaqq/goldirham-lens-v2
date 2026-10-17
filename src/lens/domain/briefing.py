"""The typed briefing document. Renderers are pure functions of this; replay compares it."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from lens.domain.bars import BarQuality
from lens.domain.evaluation import EventKind
from lens.domain.holdings import MarkStatus, ReviewAction
from lens.domain.instruments import Market
from lens.domain.reasons import ReasonCode

DISCLAIMER = (
    "Research and decision support only. Not financial advice. "
    "Goldirham Lens never places trades. Targets are scenarios, and gaps can exceed a planned stop."
)


class _Doc(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Mode(StrEnum):
    DETERMINISTIC = "deterministic"
    NARRATED = "narrated"
    DEGRADED = "degraded"


class DataAsOf(_Doc):
    market: Market
    session: date | None


class DataIssue(_Doc):
    subject: str
    reasons: tuple[ReasonCode, ...]


class HoldingLine(_Doc):
    symbol: str
    name: str
    currency: str
    quantity: Decimal
    mark: Decimal | None
    mark_day: date | None
    mark_source: str | None
    mark_status: MarkStatus
    value_base: Decimal | None
    unrealized_pct: Decimal | None
    weight_pct: Decimal | None
    day_change_pct: Decimal | None
    review: ReviewAction
    review_reasons: tuple[ReasonCode, ...]
    review_stop: Decimal | None


class PortfolioSection(_Doc):
    base_currency: str
    total_base: Decimal
    fx_days: tuple[date, ...]
    excluded_from_total: tuple[str, ...]
    exposure_by_asset_class: dict[str, Decimal]
    holdings: tuple[HoldingLine, ...]


class ChangeKind(StrEnum):
    MATERIAL_MOVE = "material_move"
    NEW_SETUP = "new_setup"
    REMOVED_SETUP = "removed_setup"
    REVIEW_CHANGED = "review_changed"


class ChangeLine(_Doc):
    kind: ChangeKind
    symbol: str
    change_pct: Decimal | None = None
    previous_review: ReviewAction | None = None
    review: ReviewAction | None = None


class SetupLine(_Doc):
    symbol: str
    name: str
    strategy: str
    strategy_version: str
    currency: str
    session: date
    source: str
    quality: BarQuality
    entry: Decimal
    stop: Decimal
    t1: Decimal
    t2: Decimal
    reward_risk: Decimal
    size_pct: Decimal
    size_capped: bool
    reasons: tuple[ReasonCode, ...]


class SignalLine(_Doc):
    symbol: str
    event: EventKind
    day: date
    price: Decimal | None
    r: Decimal | None
    currency: str


class BenchmarkLine(_Doc):
    symbol: str
    name: str
    currency: str
    session: date
    close: Decimal
    change_pct: Decimal | None
    above_ma200: bool | None


class Headline(_Doc):
    title: str
    source: str


Regime = Literal["risk_on", "neutral", "risk_off", "unknown"]


class MarketContext(_Doc):
    regime: Regime
    breadth_pct: Decimal | None
    benchmarks: tuple[BenchmarkLine, ...]
    fear_greed: int | None
    fear_greed_label: str | None
    headlines: tuple[Headline, ...]


class NarrativeSection(_Doc):
    paragraphs: tuple[str, ...]
    model: str


class BriefingDocument(_Doc):
    briefing_date: date
    generated_at: datetime
    cycle_id: str
    mode: Mode
    late: bool
    detail: Literal["concise", "detailed"]
    degraded_reason: str | None
    data_as_of: tuple[DataAsOf, ...]
    data_issues: tuple[DataIssue, ...]
    sources_unavailable: tuple[str, ...]
    portfolio: PortfolioSection | None
    portfolio_note: str | None
    changes: tuple[ChangeLine, ...]
    setups: tuple[SetupLine, ...]
    open_signals: tuple[SignalLine, ...]
    market: MarketContext
    narrative: NarrativeSection | None
    strategy_versions: dict[str, str]
    disclaimer: str = DISCLAIMER

    @property
    def healthy(self) -> bool:
        return (
            not self.data_issues and not self.sources_unavailable and self.mode is not Mode.DEGRADED
        )
