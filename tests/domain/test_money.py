from __future__ import annotations

from decimal import Decimal

import pytest

from lens.domain.money import NonFiniteNumberError, TickRule, to_decimal

BURSA = TickRule.from_pairs([("1", "0.005"), ("10", "0.01"), ("100", "0.02"), (None, "0.10")])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "NaN", "Infinity", True, None, "abc"])
def test_non_finite_and_non_numeric_values_are_refused(bad: object) -> None:
    with pytest.raises(NonFiniteNumberError):
        to_decimal(bad)


def test_floats_convert_through_their_shortest_repr() -> None:
    assert to_decimal(0.1) == Decimal("0.1")


@pytest.mark.parametrize(
    ("price", "floor", "ceil", "nearest"),
    [
        ("0.9973", "0.995", "1.000", "0.995"),
        ("9.876", "9.87", "9.88", "9.88"),
        ("57.33", "57.32", "57.34", "57.32"),
        ("123.456", "123.40", "123.50", "123.50"),
    ],
)
def test_bursa_ticks_follow_the_price_band(price: str, floor: str, ceil: str, nearest: str) -> None:
    value = Decimal(price)
    assert BURSA.floor(value) == Decimal(floor)
    assert BURSA.ceil(value) == Decimal(ceil)
    assert BURSA.nearest(value) == Decimal(nearest)


def test_tick_table_must_end_unbounded() -> None:
    with pytest.raises(ValueError, match="no upper bound"):
        TickRule.from_pairs([("1", "0.01")])


def test_numpy_scalars_from_providers_convert_exactly() -> None:
    """Regression: numpy 2 reprs floats as `np.float64(...)`, which broke every Yahoo bar."""
    import numpy as np

    assert to_decimal(np.float64(123.45)) == Decimal("123.45")
    assert to_decimal(np.int64(1_000_000)) == Decimal(1_000_000)
    with pytest.raises(NonFiniteNumberError):
        to_decimal(np.float64("nan"))
