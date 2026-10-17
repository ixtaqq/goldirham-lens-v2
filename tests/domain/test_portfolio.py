from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from lens.domain.holdings import MarkStatus
from lens.domain.instruments import AssetClass
from lens.domain.portfolio import (
    FxRate,
    LedgerError,
    Mark,
    Transaction,
    TxKind,
    build_positions,
    value_portfolio,
)

D = Decimal


def tx(
    id_: int, kind: TxKind, day: str, symbol: str = "AAPL", currency: str = "USD", **kw: object
) -> Transaction:
    return Transaction(id_, symbol, kind, date.fromisoformat(day), currency, **kw)  # type: ignore[arg-type]


def test_partial_sell_with_fee_realises_fifo_pnl() -> None:
    """Scenario 10, hand-computed.

    Lot A: 10 @ 100 + fee 5 -> unit cost 100.5. Lot B: 10 @ 120 + fee 5 -> unit cost 120.5.
    Sell 15 @ 130 with fee 7.5: net proceeds 1942.5, 129.5 per unit.
    Consumes all of A (realised 10 x (129.5 - 100.5) = 290) and 5 of B (5 x (129.5 - 120.5) = 45).
    """
    positions = build_positions(
        [
            tx(1, TxKind.BUY, "2026-01-05", quantity=D(10), price=D(100), fee=D(5)),
            tx(2, TxKind.BUY, "2026-02-05", quantity=D(10), price=D(120), fee=D(5)),
            tx(3, TxKind.SELL, "2026-03-05", quantity=D(15), price=D(130), fee=D("7.5")),
        ]
    )
    position = positions["AAPL"]
    assert position.realized == D(335)
    assert position.quantity == D(5)
    assert position.cost_basis == D("602.5")
    assert [lot.quantity for lot in position.closed] == [D(10), D(5)]


def test_split_scales_open_lots_without_changing_cost_basis() -> None:
    positions = build_positions(
        [
            tx(1, TxKind.BUY, "2026-01-05", symbol="NVDA", quantity=D(3), price=D(900)),
            tx(2, TxKind.SPLIT, "2026-06-10", symbol="NVDA", ratio=D(10)),
        ]
    )
    position = positions["NVDA"]
    assert position.quantity == D(30)
    assert position.cost_basis == D(2700)


def test_selling_more_than_held_is_refused() -> None:
    with pytest.raises(LedgerError, match="only 1 held"):
        build_positions(
            [
                tx(1, TxKind.BUY, "2026-01-05", quantity=D(1), price=D(10)),
                tx(2, TxKind.SELL, "2026-01-06", quantity=D(2), price=D(10)),
            ]
        )


def test_dividends_and_fees_flow_into_realised() -> None:
    positions = build_positions(
        [
            tx(
                1,
                TxKind.BUY,
                "2026-01-05",
                symbol="1155.KL",
                currency="MYR",
                quantity=D(100),
                price=D("9.50"),
            ),
            tx(2, TxKind.DIVIDEND, "2026-04-01", symbol="1155.KL", currency="MYR", amount=D(30)),
            tx(3, TxKind.FEE, "2026-04-02", symbol="1155.KL", currency="MYR", amount=D(2)),
        ]
    )
    assert positions["1155.KL"].realized == D(28)


def test_position_without_fx_rate_is_excluded_from_the_myr_total() -> None:
    """Scenario 9."""
    positions = build_positions(
        [
            tx(1, TxKind.BUY, "2026-01-05", quantity=D(10), price=D(100)),
            tx(
                2,
                TxKind.BUY,
                "2026-01-05",
                symbol="1155.KL",
                currency="MYR",
                quantity=D(1000),
                price=D(9),
            ),
        ]
    )
    marks = {
        "AAPL": Mark(D(110), date(2026, 3, 5), "yahoo", MarkStatus.FRESH),
        "1155.KL": Mark(D(10), date(2026, 3, 5), "yahoo", MarkStatus.FRESH),
    }
    classes = {"AAPL": AssetClass.STOCK, "1155.KL": AssetClass.STOCK}

    without_fx = value_portfolio(
        positions, asset_classes=classes, marks=marks, fx={}, base_currency="MYR"
    )
    assert without_fx.total_base == D(10000)
    assert without_fx.excluded_from_total == ("AAPL",)
    aapl = next(h for h in without_fx.holdings if h.symbol == "AAPL")
    assert aapl.value_local == D(1100)
    assert aapl.value_base is None

    rate = FxRate("USD", "MYR", D("4.40"), date(2026, 3, 5), "bnm")
    with_fx = value_portfolio(
        positions, asset_classes=classes, marks=marks, fx={"USD": rate}, base_currency="MYR"
    )
    assert with_fx.total_base == D(14840)
    assert with_fx.excluded_from_total == ()
    weights = {h.symbol: h.weight_pct for h in with_fx.holdings}
    assert weights["AAPL"] == D(4840) / D(14840) * 100
    assert with_fx.fx_days == (date(2026, 3, 5),)


def test_unavailable_mark_never_uses_the_entry_price() -> None:
    positions = build_positions([tx(1, TxKind.BUY, "2026-01-05", quantity=D(10), price=D(100))])
    snapshot = value_portfolio(
        positions, asset_classes={"AAPL": AssetClass.STOCK}, marks={}, fx={}, base_currency="USD"
    )
    holding = snapshot.holdings[0]
    assert holding.mark.status is MarkStatus.UNAVAILABLE
    assert holding.value_local is None
    assert snapshot.total_base == 0
