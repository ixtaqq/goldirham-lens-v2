"""Transaction ledger, FIFO lots, and valuation in the base currency with dated FX."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum

from lens.domain.holdings import MarkStatus
from lens.domain.instruments import AssetClass
from lens.domain.money import HUNDRED, ZERO


class TxKind(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    FEE = "FEE"
    DIVIDEND = "DIVIDEND"
    SPLIT = "SPLIT"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"


class LedgerError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Transaction:
    id: int
    symbol: str
    kind: TxKind
    day: date
    currency: str
    quantity: Decimal = ZERO
    price: Decimal = ZERO
    fee: Decimal = ZERO
    amount: Decimal = ZERO
    ratio: Decimal = ZERO
    note: str | None = None


@dataclass(slots=True)
class Lot:
    opened: date
    quantity: Decimal
    unit_cost: Decimal


@dataclass(frozen=True, slots=True)
class ClosedLot:
    symbol: str
    opened: date
    closed: date
    quantity: Decimal
    cost: Decimal
    proceeds: Decimal

    @property
    def realized(self) -> Decimal:
        return self.proceeds - self.cost


@dataclass(slots=True)
class Position:
    symbol: str
    currency: str
    lots: list[Lot] = field(default_factory=list)
    closed: list[ClosedLot] = field(default_factory=list)
    dividends: Decimal = ZERO
    standalone_fees: Decimal = ZERO

    @property
    def quantity(self) -> Decimal:
        return sum((lot.quantity for lot in self.lots), ZERO)

    @property
    def cost_basis(self) -> Decimal:
        return sum((lot.quantity * lot.unit_cost for lot in self.lots), ZERO)

    @property
    def realized(self) -> Decimal:
        return sum((c.realized for c in self.closed), ZERO) + self.dividends - self.standalone_fees

    @property
    def first_opened(self) -> date | None:
        return self.lots[0].opened if self.lots else None


def _consume(position: Position, tx: Transaction, proceeds_per_unit: Decimal | None) -> None:
    remaining = tx.quantity
    if remaining > position.quantity:
        raise LedgerError(
            f"{tx.symbol}: selling {remaining} but only {position.quantity} held on {tx.day}"
        )
    net_proceeds_total = (tx.quantity * tx.price - tx.fee) if proceeds_per_unit is None else None
    while remaining > 0:
        lot = position.lots[0]
        take = min(lot.quantity, remaining)
        cost = take * lot.unit_cost
        # A transfer out has no proceeds: it leaves at cost and realises nothing.
        proceeds = cost if net_proceeds_total is None else net_proceeds_total * take / tx.quantity
        position.closed.append(ClosedLot(tx.symbol, lot.opened, tx.day, take, cost, proceeds))
        lot.quantity -= take
        remaining -= take
        if lot.quantity == 0:
            position.lots.pop(0)


def build_positions(transactions: Iterable[Transaction]) -> dict[str, Position]:
    """Replay the ledger in date order (then id) and return every position, open or closed."""
    positions: dict[str, Position] = {}
    for tx in sorted(transactions, key=lambda t: (t.day, t.id)):
        position = positions.setdefault(tx.symbol, Position(tx.symbol, tx.currency))
        if tx.currency != position.currency:
            raise LedgerError(
                f"{tx.symbol}: currency {tx.currency} differs from {position.currency}"
            )
        match tx.kind:
            case TxKind.BUY | TxKind.TRANSFER_IN:
                if tx.quantity <= 0 or tx.price < 0 or tx.fee < 0:
                    raise LedgerError(f"{tx.symbol}: invalid {tx.kind} on {tx.day}")
                unit_cost = (tx.quantity * tx.price + tx.fee) / tx.quantity
                position.lots.append(Lot(tx.day, tx.quantity, unit_cost))
            case TxKind.SELL:
                if tx.quantity <= 0 or tx.price < 0 or tx.fee < 0:
                    raise LedgerError(f"{tx.symbol}: invalid SELL on {tx.day}")
                _consume(position, tx, None)
            case TxKind.TRANSFER_OUT:
                _consume(position, tx, ZERO)
            case TxKind.FEE:
                position.standalone_fees += tx.amount
            case TxKind.DIVIDEND:
                position.dividends += tx.amount
            case TxKind.SPLIT:
                if tx.ratio <= 0:
                    raise LedgerError(f"{tx.symbol}: split ratio must be positive")
                for lot in position.lots:
                    lot.quantity *= tx.ratio
                    lot.unit_cost /= tx.ratio
    return positions


@dataclass(frozen=True, slots=True)
class Mark:
    price: Decimal | None
    day: date | None
    source: str | None
    status: MarkStatus


@dataclass(frozen=True, slots=True)
class FxRate:
    quote: str
    base: str
    rate: Decimal
    day: date
    source: str


@dataclass(frozen=True, slots=True)
class HoldingValue:
    symbol: str
    asset_class: AssetClass
    currency: str
    quantity: Decimal
    cost_basis: Decimal
    mark: Mark
    value_local: Decimal | None
    unrealized_local: Decimal | None
    unrealized_pct: Decimal | None
    value_base: Decimal | None
    fx: FxRate | None
    weight_pct: Decimal | None
    realized_local: Decimal
    opened: date | None


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    base_currency: str
    holdings: tuple[HoldingValue, ...]
    total_base: Decimal
    excluded_from_total: tuple[str, ...]
    exposure_by_asset_class: Mapping[AssetClass, Decimal]
    exposure_by_currency: Mapping[str, Decimal]
    fx_days: tuple[date, ...]


def value_portfolio(
    positions: Mapping[str, Position],
    *,
    asset_classes: Mapping[str, AssetClass],
    marks: Mapping[str, Mark],
    fx: Mapping[str, FxRate],
    base_currency: str,
) -> PortfolioSnapshot:
    """Value open positions. A position without a usable mark or FX rate is shown, never guessed."""
    rows: list[HoldingValue] = []
    total = ZERO
    excluded: list[str] = []
    for symbol, position in sorted(positions.items()):
        if position.quantity <= 0:
            continue
        mark = marks.get(symbol, Mark(None, None, None, MarkStatus.UNAVAILABLE))
        rate = None if position.currency == base_currency else fx.get(position.currency)
        value_local = unrealized = unrealized_pct = value_base = None
        if mark.price is not None and mark.status is not MarkStatus.UNAVAILABLE:
            value_local = position.quantity * mark.price
            unrealized = value_local - position.cost_basis
            if position.cost_basis > 0:
                unrealized_pct = unrealized / position.cost_basis * HUNDRED
            if position.currency == base_currency:
                value_base = value_local
            elif rate is not None:
                value_base = value_local * rate.rate
        if value_base is None:
            excluded.append(symbol)
        else:
            total += value_base
        rows.append(
            HoldingValue(
                symbol=symbol,
                asset_class=asset_classes.get(symbol, AssetClass.STOCK),
                currency=position.currency,
                quantity=position.quantity,
                cost_basis=position.cost_basis,
                mark=mark,
                value_local=value_local,
                unrealized_local=unrealized,
                unrealized_pct=unrealized_pct,
                value_base=value_base,
                fx=rate,
                weight_pct=None,
                realized_local=position.realized,
                opened=position.first_opened,
            )
        )
    by_class: dict[AssetClass, Decimal] = defaultdict(lambda: ZERO)
    by_currency: dict[str, Decimal] = defaultdict(lambda: ZERO)
    weighted: list[HoldingValue] = []
    for row in rows:
        weight = (
            row.value_base / total * HUNDRED if row.value_base is not None and total > 0 else None
        )
        weighted.append(replace(row, weight_pct=weight))
        if weight is not None:
            by_class[row.asset_class] += weight
            by_currency[row.currency] += weight
    fx_days = tuple(sorted({r.fx.day for r in rows if r.fx is not None}))
    return PortfolioSnapshot(
        base_currency,
        tuple(weighted),
        total,
        tuple(excluded),
        dict(by_class),
        dict(by_currency),
        fx_days,
    )
