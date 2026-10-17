from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from lens.domain.instruments import AssetClass, Instrument
from lens.domain.market_view import MarketView
from lens.domain.money import TickRule
from lens.domain.reasons import ReasonCode
from lens.domain.strategy.base import AssetContext, Fundamentals, RiskInputs
from lens.domain.strategy.breakout import Breakout52w, BreakoutParams
from lens.domain.strategy.pullback import PullbackInUptrend, PullbackParams
from lens.domain.strategy.registry import configure
from tests.helpers import make_bars, uptrend_then_pullback

US = TickRule.from_pairs([("1", "0.0001"), (None, "0.01")])
RISK = RiskInputs(Decimal(1), Decimal(20))


def _ctx(
    symbol: str, asset_class: AssetClass, fundamentals: Fundamentals | None = None
) -> AssetContext:
    return AssetContext(Instrument.create(symbol, asset_class), US, RISK, fundamentals)


def _view(symbol: str, closes: list[float]) -> MarketView:
    return MarketView.of(symbol, make_bars(symbol, closes, spread="0.004"), as_of=date(2030, 1, 1))


def test_pullback_in_uptrend_builds_a_setup_with_its_reasons() -> None:
    view = _view("SPY", uptrend_then_pullback())
    decision = PullbackInUptrend().decide(view, _ctx("SPY", AssetClass.ETF), PullbackParams())

    assert decision.eligible
    assert decision.setup is not None
    assert decision.setup.entry == US.nearest(view.last().close)
    assert decision.reasons[:3] == (
        ReasonCode.TREND_OK,
        ReasonCode.FLOOR_OK,
        ReasonCode.VOLATILITY_OK,
    )
    assert ReasonCode.RSI_TRIGGER in decision.reasons
    assert ReasonCode.SETUP_BUILT in decision.reasons
    assert decision.blocking_reasons == ()


def test_downtrend_is_rejected_and_every_rule_is_still_reported() -> None:
    closes = [300.0 * (0.997**i) for i in range(260)]
    decision = PullbackInUptrend().decide(
        _view("QQQ", closes), _ctx("QQQ", AssetClass.ETF), PullbackParams()
    )

    assert not decision.eligible
    assert ReasonCode.TREND_FILTER_FAILED in decision.reasons
    assert ReasonCode.VOLATILITY_OK in decision.reasons
    assert ReasonCode.TREND_FILTER_FAILED in decision.blocking_reasons


def test_stock_with_excluded_fundamentals_gets_no_setup() -> None:
    expensive = Fundamentals(Decimal(250), Decimal(10), date(2029, 12, 1))
    decision = PullbackInUptrend().decide(
        _view("NVDA", uptrend_then_pullback()),
        _ctx("NVDA", AssetClass.STOCK, expensive),
        PullbackParams(),
    )
    assert not decision.eligible
    assert ReasonCode.FUNDAMENTALS_EXCLUDED in decision.blocking_reasons


def test_stock_without_fundamentals_is_allowed_and_says_so() -> None:
    decision = PullbackInUptrend().decide(
        _view("AAPL", uptrend_then_pullback()), _ctx("AAPL", AssetClass.STOCK), PullbackParams()
    )
    assert decision.eligible
    assert ReasonCode.FUNDAMENTALS_UNAVAILABLE in decision.reasons


def test_short_history_reports_indicators_unavailable() -> None:
    decision = PullbackInUptrend().decide(
        _view("SPY", [100.0] * 50), _ctx("SPY", AssetClass.ETF), PullbackParams()
    )
    assert decision.reasons == (ReasonCode.INDICATORS_UNAVAILABLE,)


def test_breakout_needs_both_a_new_high_and_volume() -> None:
    closes = [100.0 + (i % 10) * 0.5 for i in range(270)] + [110.0]
    bars = make_bars("MSFT", closes, spread="0.002")
    loud = [*bars[:-1], replace(bars[-1], volume=Decimal(3_000_000))]
    params = BreakoutParams()
    ctx = _ctx("MSFT", AssetClass.STOCK)

    quiet = Breakout52w().decide(MarketView.of("MSFT", bars, date(2030, 1, 1)), ctx, params)
    assert quiet.reasons[:2] == (ReasonCode.BREAKOUT_TRIGGER, ReasonCode.VOLUME_NOT_CONFIRMED)
    confirmed = Breakout52w().decide(MarketView.of("MSFT", loud, date(2030, 1, 1)), ctx, params)
    assert confirmed.eligible


def test_versions_change_with_parameters_and_are_stable_otherwise() -> None:
    base = configure({"pullback_in_uptrend": (True, {})})[0]
    same = configure({"pullback_in_uptrend": (True, {})})[0]
    tighter = configure({"pullback_in_uptrend": (True, {"rsi_trigger": 30})})[0]
    assert base.version == same.version
    assert base.version != tighter.version
    assert len(base.version) == 12
