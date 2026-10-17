"""Decimal helpers. Money and prices are Decimal everywhere outside indicator maths."""

from __future__ import annotations

import numbers
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, InvalidOperation

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)


class NonFiniteNumberError(ValueError):
    pass


def to_decimal(value: object) -> Decimal:
    """Convert a number or numeric string to a finite Decimal, refusing NaN and infinity."""
    if isinstance(value, bool):
        raise NonFiniteNumberError("booleans are not numbers")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, numbers.Integral):
        result = Decimal(int(value))
    elif isinstance(value, numbers.Real):
        # float() first: numpy scalars repr as `np.float64(...)`, not as a number
        result = Decimal(repr(float(value)))
    elif isinstance(value, str):
        try:
            result = Decimal(value.strip())
        except InvalidOperation as error:
            raise NonFiniteNumberError(f"not a number: {value!r}") from error
    else:
        raise NonFiniteNumberError(f"not a number: {value!r}")
    if not result.is_finite():
        raise NonFiniteNumberError(f"not finite: {value!r}")
    return result


@dataclass(frozen=True, slots=True)
class TickBand:
    below: Decimal | None
    tick: Decimal


@dataclass(frozen=True, slots=True)
class TickRule:
    """Price increments by price band. Bands are ordered from the lowest price upward."""

    bands: tuple[TickBand, ...]

    @classmethod
    def from_pairs(cls, pairs: Sequence[tuple[str | None, str]]) -> TickRule:
        bands = tuple(
            TickBand(None if below is None else Decimal(below), Decimal(tick))
            for below, tick in pairs
        )
        if not bands or bands[-1].below is not None:
            raise ValueError("the last tick band must have no upper bound")
        return cls(bands)

    def tick_for(self, price: Decimal) -> Decimal:
        for band in self.bands[:-1]:
            if band.below is not None and price < band.below:
                return band.tick
        return self.bands[-1].tick

    def floor(self, price: Decimal) -> Decimal:
        return _quantize(price, self.tick_for(price), ROUND_FLOOR)

    def ceil(self, price: Decimal) -> Decimal:
        return _quantize(price, self.tick_for(price), ROUND_CEILING)

    def nearest(self, price: Decimal) -> Decimal:
        return _quantize(price, self.tick_for(price), ROUND_HALF_EVEN)


def _quantize(price: Decimal, tick: Decimal, rounding: str) -> Decimal:
    steps = (price / tick).to_integral_value(rounding=rounding)
    return (steps * tick).quantize(tick)
