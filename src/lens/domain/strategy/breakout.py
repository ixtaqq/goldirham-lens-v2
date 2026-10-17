"""Close above the prior 52-week high on confirming volume. Research only until backtested."""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from pydantic import Field

from lens.domain.indicators import atr, compute_indicators, prior_high, sma
from lens.domain.market_view import MarketView
from lens.domain.reasons import ReasonCode
from lens.domain.risk import build_long_setup
from lens.domain.strategy.base import (
    AssetContext,
    Decision,
    LongSetupParams,
    Setup,
    strategy_version,
)


class BreakoutParams(LongSetupParams):
    lookback_sessions: int = Field(252, ge=20)
    volume_multiple: Decimal = Field(Decimal("1.5"), gt=0)
    volume_average_sessions: int = Field(50, ge=5)


class Breakout52w:
    name: ClassVar[str] = "breakout_52w"
    code_version: ClassVar[str] = "1"
    params_model: ClassVar[type[LongSetupParams]] = BreakoutParams

    def decide(self, view: MarketView, ctx: AssetContext, params: LongSetupParams) -> Decision:
        assert isinstance(params, BreakoutParams)
        version = strategy_version(self.name, params, self.code_version)
        closes, highs, lows, volumes = view.closes(), view.highs(), view.lows(), view.volumes()
        indicators = compute_indicators(view).as_dict() if closes else {}
        session = view.last().day

        def decision(reasons: list[ReasonCode], setup: Setup | None = None) -> Decision:
            return Decision(
                view.symbol, session, self.name, version, tuple(reasons), setup, indicators
            )

        ceiling = prior_high(highs, params.lookback_sessions)
        average_range = atr(highs, lows, closes, params.atr_period)
        average_volume = sma(volumes[:-1], params.volume_average_sessions)
        if ceiling is None or average_range is None or average_volume is None:
            return decision([ReasonCode.INDICATORS_UNAVAILABLE])

        reasons: list[ReasonCode] = []
        broke_out = closes[-1] > ceiling
        reasons.append(ReasonCode.BREAKOUT_TRIGGER if broke_out else ReasonCode.NO_BREAKOUT)
        confirmed = average_volume > 0 and volumes[-1] >= average_volume * float(
            params.volume_multiple
        )
        if not confirmed:
            reasons.append(ReasonCode.VOLUME_NOT_CONFIRMED)
        if not (broke_out and confirmed):
            return decision(reasons)

        t1_r, t2_r = params.targets_r
        built = build_long_setup(
            view.last().close,
            average_range,
            stop_multiple=params.atr_stop_multiple,
            t1_r=t1_r,
            t2_r=t2_r,
            min_reward_risk=params.min_reward_risk,
            risk=ctx.risk,
            tick_rule=ctx.tick_rule,
            method=(
                f"52w breakout, ATR{params.atr_period} x{params.atr_stop_multiple} stop, "
                f"{t1_r}R/{t2_r}R"
            ),
        )
        if isinstance(built, ReasonCode):
            return decision([*reasons, built])
        reasons.append(ReasonCode.SETUP_BUILT)
        if built.size_capped:
            reasons.append(ReasonCode.CONCENTRATION_CAP_REACHED)
        return decision(reasons, built)
