"""Pullback in an established uptrend. Reproduces the v1 rule set as the baseline strategy."""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from pydantic import Field, model_validator

from lens.domain.indicators import atr, compute_indicators, last_swing_low, rsi, sma
from lens.domain.market_view import MarketView
from lens.domain.reasons import ReasonCode
from lens.domain.risk import build_long_setup
from lens.domain.strategy.base import (
    AssetContext,
    Decision,
    LongSetupParams,
    Setup,
    StrategyParams,
    strategy_version,
)


class FundamentalLimits(StrategyParams):
    max_pe: Decimal = Decimal(100)
    min_revenue_growth_pct: Decimal = Decimal(-20)


class PullbackParams(LongSetupParams):
    ma_fast: int = Field(50, ge=5)
    ma_slow: int = Field(200, ge=20)
    trend_multiple: Decimal = Field(Decimal("1.05"), gt=0)
    floor_vs_ma_slow: Decimal = Field(Decimal("0.85"), gt=0)
    max_atr_pct: Decimal = Field(Decimal("8.0"), gt=0)
    rsi_period: int = Field(14, ge=2)
    rsi_trigger: Decimal = Field(Decimal(25), gt=0, lt=100)
    support_distance_pct: Decimal = Field(Decimal("1.0"), gt=0)
    swing_radius: int = Field(2, ge=1)
    fundamentals: FundamentalLimits = FundamentalLimits()

    @model_validator(mode="after")
    def _ordered(self) -> PullbackParams:
        if self.ma_fast >= self.ma_slow:
            raise ValueError("ma_fast must be shorter than ma_slow")
        return self


class PullbackInUptrend:
    name: ClassVar[str] = "pullback_in_uptrend"
    code_version: ClassVar[str] = "1"
    params_model: ClassVar[type[LongSetupParams]] = PullbackParams

    def decide(self, view: MarketView, ctx: AssetContext, params: LongSetupParams) -> Decision:
        assert isinstance(params, PullbackParams)
        version = strategy_version(self.name, params, self.code_version)
        closes, highs, lows = view.closes(), view.highs(), view.lows()
        indicators = compute_indicators(view).as_dict() if closes else {}
        fast = sma(closes, params.ma_fast)
        slow = sma(closes, params.ma_slow)
        average_range = atr(highs, lows, closes, params.atr_period)
        momentum = rsi(closes, params.rsi_period)
        support = last_swing_low(lows, params.swing_radius)
        session = view.last().day

        def decision(reasons: list[ReasonCode], setup: Setup | None = None) -> Decision:
            return Decision(
                symbol=view.symbol,
                session=session,
                strategy=self.name,
                strategy_version=version,
                reasons=tuple(reasons),
                setup=setup,
                indicators=indicators,
            )

        if fast is None or slow is None or average_range is None or momentum is None:
            return decision([ReasonCode.INDICATORS_UNAVAILABLE])

        close = view.last().close
        close_f = float(close)
        reasons: list[ReasonCode] = []
        failed = False

        def check(passed: bool, ok: ReasonCode, fail: ReasonCode) -> None:
            nonlocal failed
            reasons.append(ok if passed else fail)
            failed = failed or not passed

        check(
            fast > slow * float(params.trend_multiple),
            ReasonCode.TREND_OK,
            ReasonCode.TREND_FILTER_FAILED,
        )
        check(
            close_f >= slow * float(params.floor_vs_ma_slow),
            ReasonCode.FLOOR_OK,
            ReasonCode.BELOW_FLOOR,
        )
        check(
            average_range / close_f * 100 <= float(params.max_atr_pct),
            ReasonCode.VOLATILITY_OK,
            ReasonCode.VOLATILITY_TOO_HIGH,
        )
        oversold = momentum < float(params.rsi_trigger)
        near_support = (
            support is not None
            and support > 0
            and abs(close_f / support - 1) * 100 < float(params.support_distance_pct)
        )
        if oversold:
            reasons.append(ReasonCode.RSI_TRIGGER)
        if near_support:
            reasons.append(ReasonCode.SUPPORT_TRIGGER)
        if not (oversold or near_support):
            reasons.append(ReasonCode.NO_PULLBACK_TRIGGER)
            failed = True

        if ctx.is_stock:
            limits = params.fundamentals
            data = ctx.fundamentals
            if data is None or (data.pe_ratio is None and data.revenue_growth_pct is None):
                reasons.append(ReasonCode.FUNDAMENTALS_UNAVAILABLE)
            else:
                excluded = (
                    data.pe_ratio is not None
                    and (data.pe_ratio <= 0 or data.pe_ratio > limits.max_pe)
                ) or (
                    data.revenue_growth_pct is not None
                    and data.revenue_growth_pct < limits.min_revenue_growth_pct
                )
                check(not excluded, ReasonCode.FUNDAMENTALS_OK, ReasonCode.FUNDAMENTALS_EXCLUDED)

        if failed:
            return decision(reasons)

        t1_r, t2_r = params.targets_r
        built = build_long_setup(
            close,
            average_range,
            stop_multiple=params.atr_stop_multiple,
            t1_r=t1_r,
            t2_r=t2_r,
            min_reward_risk=params.min_reward_risk,
            risk=ctx.risk,
            tick_rule=ctx.tick_rule,
            method=(
                f"ATR{params.atr_period} x{params.atr_stop_multiple} stop, "
                f"{t1_r}R/{t2_r}R targets, {ctx.risk.risk_per_trade_pct}% risk, "
                f"{ctx.risk.max_position_pct}% cap"
            ),
        )
        if isinstance(built, ReasonCode):
            return decision([*reasons, built])
        reasons.append(ReasonCode.SETUP_BUILT)
        if built.size_capped:
            reasons.append(ReasonCode.CONCENTRATION_CAP_REACHED)
        return decision(reasons, built)
