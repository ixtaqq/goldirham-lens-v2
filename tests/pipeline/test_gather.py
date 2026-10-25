"""The pure parts of gather."""

from __future__ import annotations

from lens.domain.instruments import AssetClass, Instrument
from lens.pipeline.gather import universe
from lens.settings import load_settings


def test_a_held_benchmark_off_the_watchlist_is_collected_once() -> None:
    settings = load_settings()
    spy = Instrument.create("SPY", AssetClass.ETF, "SPDR S&P 500 ETF")
    watched = [i for i in settings.instruments() if i.symbol != "SPY"]

    symbols = [i.symbol for i in universe(settings, watched, {"SPY"}, {"SPY": spy})]

    assert symbols.count("SPY") == 1
    assert len(symbols) == len(set(symbols))
    assert symbols[: len(watched)] == [i.symbol for i in watched]
