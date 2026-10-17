from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lens.domain.instruments import AssetClass, Instrument
from lens.domain.market_view import MarketView
from lens.domain.money import TickRule
from lens.domain.reasons import PASS_CODES, ReasonCode


class StrategyParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LongSetupParams(StrategyParams):
    """Parameters every long-setup strategy shares: the stop, targets and expiry."""

    atr_period: int = Field(14, ge=2)
    atr_stop_multiple: Decimal = Field(Decimal("2.0"), gt=0)
    targets_r: tuple[Decimal, Decimal] = (Decimal("1.5"), Decimal("3.0"))
    min_reward_risk: Decimal = Field(Decimal("2.0"), gt=0)
    expiry_days: int = Field(120, ge=1)

    @model_validator(mode="after")
    def _targets_increase(self) -> LongSetupParams:
        if not (0 < self.targets_r[0] < self.targets_r[1]):
            raise ValueError("targets_r must be positive and increasing")
        return self


@dataclass(frozen=True, slots=True)
class Fundamentals:
    pe_ratio: Decimal | None
    revenue_growth_pct: Decimal | None
    as_of: date


@dataclass(frozen=True, slots=True)
class RiskInputs:
    risk_per_trade_pct: Decimal
    max_position_pct: Decimal


@dataclass(frozen=True, slots=True)
class AssetContext:
    instrument: Instrument
    tick_rule: TickRule
    risk: RiskInputs
    fundamentals: Fundamentals | None

    @property
    def is_stock(self) -> bool:
        return self.instrument.asset_class is AssetClass.STOCK


@dataclass(frozen=True, slots=True)
class Setup:
    """A long setup. Every level is quantised to the instrument's price increment."""

    entry: Decimal
    stop: Decimal
    t1: Decimal
    t2: Decimal
    reward_risk: Decimal
    size_pct: Decimal
    size_capped: bool
    method: str


@dataclass(frozen=True, slots=True)
class Decision:
    symbol: str
    session: date
    strategy: str
    strategy_version: str
    reasons: tuple[ReasonCode, ...]
    setup: Setup | None
    indicators: Mapping[str, float | int | None]

    @property
    def eligible(self) -> bool:
        return self.setup is not None

    @property
    def blocking_reasons(self) -> tuple[ReasonCode, ...]:
        return tuple(code for code in self.reasons if code not in PASS_CODES)


class Strategy(Protocol):
    name: ClassVar[str]
    code_version: ClassVar[str]
    params_model: ClassVar[type[LongSetupParams]]

    def decide(self, view: MarketView, ctx: AssetContext, params: LongSetupParams) -> Decision: ...


def strategy_version(name: str, params: StrategyParams, code_version: str) -> str:
    """A short, stable hash of the strategy name, its parameters and its rule code version."""
    payload = json.dumps(
        {"name": name, "code": code_version, "params": params.model_dump(mode="json")},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:12]
