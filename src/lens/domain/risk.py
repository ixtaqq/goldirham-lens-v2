"""Setup arithmetic. All levels are quantised before any check, so checks see real prices."""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

from lens.domain.money import HUNDRED, TickRule, to_decimal
from lens.domain.reasons import ReasonCode
from lens.domain.strategy.base import RiskInputs, Setup

SIZE_QUANTUM = Decimal("0.01")
# Rounding the stop down to the price increment may widen the risk; beyond 1.5x the ATR rule,
# the setup no longer means what its method says.
MAX_STOP_WIDENING = Decimal("1.5")


def build_long_setup(
    close: Decimal,
    atr: float,
    *,
    stop_multiple: Decimal,
    t1_r: Decimal,
    t2_r: Decimal,
    min_reward_risk: Decimal,
    risk: RiskInputs,
    tick_rule: TickRule,
    method: str,
) -> Setup | ReasonCode:
    """Build a long setup, or return the reason it cannot exist."""
    if close <= 0 or atr <= 0:
        return ReasonCode.INDICATORS_UNAVAILABLE
    if not (0 < t1_r < t2_r):
        raise ValueError("target multiples must be positive and increasing")
    entry = tick_rule.nearest(close)
    intended_risk = to_decimal(atr) * stop_multiple
    raw_stop = entry - intended_risk
    if raw_stop <= 0:
        return ReasonCode.STOP_NOT_POSITIVE
    stop = tick_rule.floor(raw_stop)
    if stop <= 0:
        return ReasonCode.STOP_NOT_POSITIVE
    r_unit = entry - stop
    if r_unit <= 0 or r_unit > intended_risk * MAX_STOP_WIDENING:
        return ReasonCode.PRECISION_TOO_COARSE
    t1 = tick_rule.floor(entry + t1_r * r_unit)
    t2 = tick_rule.floor(entry + t2_r * r_unit)
    if not (stop < entry < t1 < t2):
        return ReasonCode.PRECISION_TOO_COARSE
    reward_risk = ((t2 - entry) / r_unit).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
    if reward_risk < min_reward_risk:
        return ReasonCode.REWARD_RISK_BELOW_MINIMUM
    stop_distance_pct = r_unit / entry * HUNDRED
    uncapped = (risk.risk_per_trade_pct / stop_distance_pct * HUNDRED).quantize(
        SIZE_QUANTUM, rounding=ROUND_FLOOR
    )
    size_pct = min(uncapped, risk.max_position_pct)
    return Setup(
        entry=entry,
        stop=stop,
        t1=t1,
        t2=t2,
        reward_risk=reward_risk,
        size_pct=size_pct,
        size_capped=uncapped > risk.max_position_pct,
        method=method,
    )
