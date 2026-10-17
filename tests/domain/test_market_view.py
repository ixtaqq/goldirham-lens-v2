from __future__ import annotations

from datetime import date

import pytest

from lens.domain.market_view import LookAheadError, MarketView
from tests.helpers import make_bars


def test_view_never_contains_bars_after_as_of() -> None:
    bars = make_bars("X", [1, 2, 3, 4, 5], start=date(2026, 3, 2))
    view = MarketView.of("X", bars, as_of=date(2026, 3, 4))

    assert view.days() == [date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)]
    assert view.last().close == 3


def test_asking_for_a_future_session_raises() -> None:
    view = MarketView.of(
        "X", make_bars("X", [1, 2], start=date(2026, 3, 2)), as_of=date(2026, 3, 3)
    )
    with pytest.raises(LookAheadError):
        view.bar_on(date(2026, 3, 4))
    assert view.bar_on(date(2026, 3, 1)) is None


def test_a_bar_for_another_symbol_is_rejected() -> None:
    with pytest.raises(ValueError, match="bar for Y"):
        MarketView.of("X", make_bars("Y", [1]), as_of=date(2030, 1, 1))
