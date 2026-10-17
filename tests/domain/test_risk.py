from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from lens.domain.money import TickRule
from lens.domain.reasons import ReasonCode
from lens.domain.risk import build_long_setup
from lens.domain.strategy.base import RiskInputs, Setup

CRYPTO_TICKS = TickRule.from_pairs([("1", "0.00001"), ("100", "0.001"), (None, "0.01")])
US_TICKS = TickRule.from_pairs([("1", "0.0001"), (None, "0.01")])
RISK = RiskInputs(Decimal("1.0"), Decimal("20.0"))


def _build(
    close: Decimal, atr: float, ticks: TickRule = CRYPTO_TICKS, risk: RiskInputs = RISK
) -> Setup | ReasonCode:
    return build_long_setup(
        close,
        atr,
        stop_multiple=Decimal(2),
        t1_r=Decimal("1.5"),
        t2_r=Decimal(3),
        min_reward_risk=Decimal(2),
        risk=risk,
        tick_rule=ticks,
        method="test",
    )


def test_known_setup_levels() -> None:
    setup = _build(Decimal("100.00"), 2.5, US_TICKS)
    assert isinstance(setup, Setup)
    assert (setup.entry, setup.stop, setup.t1, setup.t2) == (
        Decimal("100.00"),
        Decimal("95.00"),
        Decimal("107.50"),
        Decimal("115.00"),
    )
    assert setup.reward_risk == Decimal("3.00")
    # 1% risk over a 5% stop is exactly the 20% cap, which is not over it
    assert setup.size_pct == Decimal("20.00")
    assert setup.size_capped is False


def test_tighter_stop_is_capped_by_concentration() -> None:
    setup = _build(Decimal("100.00"), 2.0, US_TICKS)
    assert isinstance(setup, Setup)
    assert setup.stop == Decimal("96.00")
    assert setup.size_pct == Decimal("20.00")
    assert setup.size_capped is True


def test_low_priced_asset_with_tiny_atr_is_rejected_not_collapsed() -> None:
    """Scenario 12: close 0.000151 and ATR 0.000001 would collapse at the price increment."""
    assert _build(Decimal("0.000151"), 0.000001) is ReasonCode.PRECISION_TOO_COARSE


def test_stop_at_or_below_zero_is_rejected() -> None:
    assert _build(Decimal("10"), 6.0) is ReasonCode.STOP_NOT_POSITIVE


@settings(max_examples=400, deadline=None)
@given(
    close=st.decimals(
        min_value=Decimal("0.00001"), max_value=Decimal(1_000_000), places=5, allow_nan=False
    ),
    atr_fraction=st.floats(min_value=0.0005, max_value=0.45),
    risk_pct=st.decimals(min_value=Decimal("0.1"), max_value=Decimal(5), places=2),
    cap=st.decimals(min_value=Decimal(1), max_value=Decimal(100), places=1),
)
def test_every_setup_is_ordered_capped_and_within_risk(
    close: Decimal, atr_fraction: float, risk_pct: Decimal, cap: Decimal
) -> None:
    result = _build(close, float(close) * atr_fraction, CRYPTO_TICKS, RiskInputs(risk_pct, cap))
    if isinstance(result, ReasonCode):
        assert result in {
            ReasonCode.PRECISION_TOO_COARSE,
            ReasonCode.STOP_NOT_POSITIVE,
            ReasonCode.REWARD_RISK_BELOW_MINIMUM,
        }
        return
    assert 0 < result.stop < result.entry < result.t1 < result.t2
    assert result.size_pct <= cap
    # size% x (stop distance / entry) <= risk%, cross-multiplied so no division rounds the check
    assert result.size_pct * (result.entry - result.stop) <= risk_pct * result.entry
    assert result.reward_risk >= 2
    for level in (result.entry, result.stop, result.t1, result.t2):
        assert CRYPTO_TICKS.nearest(level) == level
