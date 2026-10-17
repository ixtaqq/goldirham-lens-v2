"""Guard paths: each refusal, short history and degenerate input returns its stated result."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from lens.domain.bars import BarQuality
from lens.domain.evaluation import Levels, SignalState, SignalStatus, advance
from lens.domain.facts import Fact, FactScope
from lens.domain.holdings import HoldingRules, MarkStatus, ReviewAction, review_holding
from lens.domain.indicators import (
    atr,
    bollinger,
    ema_series,
    last_swing_high,
    macd,
    prior_high,
    realized_volatility,
    rsi,
    sma_series,
    trailing_return,
)
from lens.domain.instruments import AssetClass, Instrument, Market, UnsupportedMarketError
from lens.domain.market_view import MarketView
from lens.domain.money import TickRule
from lens.domain.portfolio import LedgerError, Transaction, TxKind, build_positions
from lens.domain.reasons import LABELS, ReasonCode, label
from lens.domain.risk import build_long_setup
from lens.domain.scorecard import ExitModel, SignalRecord, build_scorecard
from lens.domain.sessions import Session
from lens.domain.strategy.base import RiskInputs
from lens.domain.strategy.pullback import PullbackParams
from lens.domain.strategy.registry import UnknownStrategyError, configure
from lens.domain.validation import is_suspect_jump, shape_is_valid
from tests.helpers import bar, make_bars

TICKS = TickRule.from_pairs([(None, "0.01")])
RISK = RiskInputs(Decimal(1), Decimal(20))
D = Decimal


def _setup(close: str, atr_value: float, **kw: object) -> object:
    args: dict[str, object] = {
        "stop_multiple": D(2),
        "t1_r": D("1.5"),
        "t2_r": D(3),
        "min_reward_risk": D(2),
        "risk": RISK,
        "tick_rule": TICKS,
        "method": "t",
    }
    args.update(kw)
    return build_long_setup(D(close), atr_value, **args)  # type: ignore[arg-type]


def test_setup_refusals() -> None:
    assert _setup("0", 1.0) is ReasonCode.INDICATORS_UNAVAILABLE
    assert _setup("100", 0.0) is ReasonCode.INDICATORS_UNAVAILABLE
    assert _setup("100", 2.0, min_reward_risk=D(5)) is ReasonCode.REWARD_RISK_BELOW_MINIMUM
    assert _setup("0.05", 0.0001) is ReasonCode.PRECISION_TOO_COARSE
    with pytest.raises(ValueError, match="increasing"):
        _setup("100", 2.0, t1_r=D(3), t2_r=D(2))


def test_strategy_params_validate_their_own_shape() -> None:
    with pytest.raises(ValidationError, match="increasing"):
        PullbackParams(targets_r=(D(3), D(1)))
    with pytest.raises(ValidationError, match="shorter"):
        PullbackParams(ma_fast=200, ma_slow=50)
    with pytest.raises(UnknownStrategyError):
        configure({"no_such_strategy": (True, {})})


def test_market_view_edges() -> None:
    days = [date(2026, 3, 2), date(2026, 3, 4)]
    view = MarketView.of("X", make_bars("X", [1, 2], days=days), as_of=date(2026, 3, 9))
    assert view.bar_on(date(2026, 3, 3)) is None
    assert view.bar_on(date(2026, 3, 4)).close == 2  # type: ignore[union-attr]
    assert len(view.bars) == 2
    assert [b.day for b in view] == days
    with pytest.raises(LookupError):
        MarketView.of("X", [], as_of=date(2026, 3, 9)).last()


def test_bar_shape_and_jump_edges() -> None:
    day = date(2026, 3, 2)
    assert not shape_is_valid(bar("X", day, "1", "1", "0", "1"))
    assert not shape_is_valid(bar("X", day, "1", "1", "1", "1", "-5"))
    good = bar("X", day, "100", "131", "100", "130", "0")
    assert is_suspect_jump(D(100), good, threshold_pct=D(20), average_volume=D(0))
    assert not is_suspect_jump(
        D(100), bar("X", day, "100", "101", "99", "100.5"), threshold_pct=D(20), average_volume=None
    )


def test_indicator_short_history_is_none() -> None:
    assert sma_series([1.0, 2.0], 5) == [None, None]
    assert ema_series([1.0], 3) == [None]
    assert atr([1.0], [1.0], [1.0], 14) is None
    assert macd([1.0] * 10) is None
    assert bollinger([1.0] * 5) is None
    assert prior_high([1.0], 5) is None
    assert realized_volatility([1.0, 0.0, 1.0] * 10, 20) is None
    assert trailing_return([0.0, 1.0], 1) is None
    assert last_swing_high([1.0, 2.0, 3.0, 2.0, 1.0], 2) == 3.0
    assert rsi([5.0] * 20, 14) == 50.0


def test_fact_rendering_by_unit() -> None:
    def fact(value: str, unit: str) -> str:
        return Fact(
            "i", FactScope.MARKET, "X", "m", D(value), unit, date(2026, 10, 15), "s"
        ).rendered()

    assert fact("1.234", "%chg") == "+1.2% (15 Oct)"
    assert fact("40.06", "%") == "40.1% (15 Oct)"
    assert fact("63", "pts") == "63 (15 Oct)"
    assert fact("82131.4", "USD") == "USD 82,131.40 (15 Oct)"
    assert fact("0.00015", "USD") == "USD 0.0002 (15 Oct)"


def test_ledger_refuses_inconsistent_entries() -> None:
    def tx(kind: TxKind, **kw: object) -> Transaction:
        values: dict[str, object] = {"quantity": D(1), "price": D(10)}
        values.update(kw)
        return Transaction(1, "X", kind, date(2026, 1, 5), kw.pop("currency", "USD"), **values)  # type: ignore[arg-type]

    with pytest.raises(LedgerError, match="invalid"):
        build_positions([tx(TxKind.BUY, quantity=D(0))])
    with pytest.raises(LedgerError, match="invalid SELL"):
        build_positions([tx(TxKind.SELL, price=D(-1))])
    with pytest.raises(LedgerError, match="split ratio"):
        build_positions([tx(TxKind.BUY), tx(TxKind.SPLIT, ratio=D(0))])
    with pytest.raises(LedgerError, match="currency"):
        build_positions([tx(TxKind.BUY), replace(tx(TxKind.BUY), id=2, currency="MYR")])


def test_transfers_move_lots_without_realising() -> None:
    positions = build_positions(
        [
            Transaction(1, "X", TxKind.TRANSFER_IN, date(2026, 1, 5), "USD", D(10), D(5)),
            Transaction(2, "X", TxKind.TRANSFER_OUT, date(2026, 2, 5), "USD", D(4)),
        ]
    )
    assert positions["X"].quantity == D(6)
    assert positions["X"].realized == 0


def test_evaluation_edges() -> None:
    finished = SignalState(status=SignalStatus.STOPPED)
    levels = Levels(D(100), D(95), D(105), D(110))
    assert advance(
        levels,
        finished,
        signal_day=date(2026, 1, 1),
        expiry_days=10,
        expected_sessions=[],
        bars=[],
        today=date(2026, 1, 2),
    ) == (finished, [])
    with pytest.raises(ValueError, match="below entry"):
        advance(
            Levels(D(100), D(100), D(105), D(110)),
            SignalState(),
            signal_day=date(2026, 1, 1),
            expiry_days=10,
            expected_sessions=[],
            bars=[],
            today=date(2026, 1, 2),
        )


def test_unavailable_mark_is_reviewed() -> None:
    view = MarketView.of("X", make_bars("X", [10.0] * 30), as_of=date(2030, 1, 1))
    review = review_holding(
        view,
        entry_day=view.days()[0],
        weight_pct=None,
        mark_status=MarkStatus.UNAVAILABLE,
        rules=HoldingRules(D(3), 3, D(25), D(20)),
    )
    assert review.action is ReviewAction.REVIEW
    assert review.reasons[0] is ReasonCode.MARK_UNAVAILABLE


def test_small_resolved_sample_has_no_quartiles() -> None:
    records = [
        SignalRecord(
            date(2026, 1, 1 + i),
            SignalStatus.T2_HIT,
            True,
            D(3),
            D("2.25"),
            date(2026, 1, 9 + i),
            D(3),
            D(0),
        )
        for i in range(3)
    ]
    card = build_scorecard(
        records,
        as_of=date(2026, 6, 1),
        window_days=365,
        min_sample=2,
        exit_model=ExitModel.FULL_TO_T2,
    )
    assert card.mfe_quartiles is None
    assert card.expectancy == D("3.00")


def test_instruments_sessions_and_labels() -> None:
    assert Instrument.create(" spy ", AssetClass.ETF).name == "SPY"
    assert Instrument.create("^KLSE", AssetClass.ETF).market is Market.XKLS
    with pytest.raises(UnsupportedMarketError):
        Instrument.create("BTC", AssetClass.CRYPTO)
    session = Session(
        Market.XNYS,
        date(2026, 10, 15),
        datetime(2026, 10, 15, 13, 30, tzinfo=UTC),
        datetime(2026, 10, 15, 20, 0, tzinfo=UTC),
    )
    assert session.is_closed(datetime(2026, 10, 15, 20, 0, tzinfo=UTC))
    assert not session.is_closed(datetime(2026, 10, 15, 19, 59, tzinfo=UTC))
    assert all(label(code) == LABELS[code] for code in ReasonCode)
    assert make_bars("X", [1.0], quality=BarQuality.SUSPECT)[0].usable is False
