"""Provider adapters against recorded responses (no network), plus opt-in live checks."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pandas as pd
import pytest
import respx

from lens.data.calendars import CryptoCalendar, calendar_for
from lens.data.collect import Collector, calendar_gaps
from lens.data.providers.alphavantage import AlphaVantageProvider, parse_alphavantage
from lens.data.providers.base import ProviderBars, ProviderError
from lens.data.providers.context import parse_fear_greed, parse_feed
from lens.data.providers.exchanges import BINANCE_URL, BinanceProvider, CoinbaseProvider
from lens.data.providers.fx import BNM_URL, FRANKFURTER_URL, fetch_myr_rate
from lens.data.providers.yahoo import parse_history
from lens.domain.bars import BarQuality
from lens.domain.instruments import AssetClass, Instrument, Market
from lens.settings import load_settings
from tests.helpers import make_bars

BTC = Instrument.create("BTC-USD", AssetClass.CRYPTO)
BNB = Instrument.create("BNB-USD", AssetClass.CRYPTO)
AAPL = Instrument.create("AAPL", AssetClass.STOCK)


def _ts(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp())


@respx.mock
async def test_coinbase_candles_parse_newest_first_rows() -> None:
    respx.get(url__startswith="https://api.exchange.coinbase.com/products/BTC-USD/candles").mock(
        return_value=httpx.Response(
            200,
            json=[
                [_ts("2026-10-15"), 80000, 82500, 81000, 82131.46, 1234.5],
                [_ts("2026-10-14"), 79000, 81500, 80000, 81000.0, 1100.0],
            ],
        )
    )
    result = await CoinbaseProvider().fetch_daily(BTC, date(2026, 10, 14), date(2026, 10, 15))
    assert [(b.day, b.close) for b in result.bars] == [
        (date(2026, 10, 14), Decimal("81000.0")),
        (date(2026, 10, 15), Decimal("82131.46")),
    ]
    assert result.bars[1].low == Decimal(80000)


@respx.mock
async def test_coinbase_server_error_is_retried_then_raised() -> None:
    route = respx.get(url__startswith="https://api.exchange.coinbase.com").mock(
        return_value=httpx.Response(503)
    )
    provider = CoinbaseProvider()
    with pytest.raises(ProviderError, match="HTTP 503"):
        await provider._window(httpx.AsyncClient(), "BTC-USD", date(2026, 10, 1), date(2026, 10, 2))
    assert route.call_count == 3


@respx.mock
async def test_binance_klines_map_usd_to_usdt() -> None:
    route = respx.get(BINANCE_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                [
                    _ts("2026-10-15") * 1000,
                    "600.1",
                    "612.0",
                    "590.5",
                    "605.25",
                    "50000.0",
                    0,
                    "0",
                    0,
                    "0",
                    "0",
                    "0",
                ],
            ],
        )
    )
    result = await BinanceProvider().fetch_daily(BNB, date(2026, 10, 15), date(2026, 10, 15))
    assert route.calls.last.request.url.params["symbol"] == "BNBUSDT"
    assert result.bars[0].close == Decimal("605.25")


def test_alpha_vantage_rate_limit_note_is_a_clear_refusal() -> None:
    with pytest.raises(ProviderError, match="request refused"):
        parse_alphavantage(
            "AAPL",
            {"Note": "Thank you for using Alpha Vantage! Our standard API rate limit..."},
            date(2026, 10, 1),
            date(2026, 10, 15),
        )


def test_alpha_vantage_series_is_filtered_to_the_window() -> None:
    payload = {
        "Time Series (Daily)": {
            "2026-10-15": {
                "1. open": "250.0",
                "2. high": "252.5",
                "3. low": "248.0",
                "4. close": "251.2",
                "5. volume": "123",
            },
            "2026-09-01": {
                "1. open": "230.0",
                "2. high": "231.0",
                "3. low": "229.0",
                "4. close": "230.5",
                "5. volume": "99",
            },
        }
    }
    result = parse_alphavantage("AAPL", payload, date(2026, 10, 1), date(2026, 10, 15))
    assert [(b.day, b.close) for b in result.bars] == [(date(2026, 10, 15), Decimal("251.2"))]


async def test_alpha_vantage_without_a_key_fails_without_a_request() -> None:
    with pytest.raises(ProviderError, match="ALPHA_VANTAGE_API_KEY"):
        await AlphaVantageProvider(None).fetch_daily(AAPL, date(2026, 10, 1), date(2026, 10, 15))


def test_yahoo_history_frame_parses_bars_and_splits() -> None:
    index = pd.DatetimeIndex(["2026-06-09", "2026-06-10"], tz="America/New_York")
    frame = pd.DataFrame(
        {
            "Open": [1200.0, 120.0],
            "High": [1210.0, 122.0],
            "Low": [1190.0, 119.0],
            "Close": [1205.0, 121.0],
            "Volume": [1000, 10000],
            "Dividends": [0.0, 0.0],
            "Stock Splits": [0.0, 10.0],
        },
        index=index,
    )
    result = parse_history("NVDA", frame)
    assert [b.close for b in result.bars] == [Decimal("1205.0"), Decimal("121.0")]
    assert result.splits == {date(2026, 6, 10): Decimal("10.0")}


@respx.mock
async def test_fx_falls_back_from_bnm_to_ecb() -> None:
    respx.get(BNM_URL.format(currency="USD")).mock(return_value=httpx.Response(500))
    respx.get(FRANKFURTER_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "amount": 1.0,
                "base": "USD",
                "date": "2026-10-15",
                "rates": {"MYR": 4.4213},
            },
        )
    )
    rate = await fetch_myr_rate("USD")
    assert (rate.rate, rate.day, rate.source) == (Decimal("4.4213"), date(2026, 10, 15), "ecb")


@respx.mock
async def test_fx_bnm_middle_rate_per_unit() -> None:
    respx.get(BNM_URL.format(currency="JPY")).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "currency_code": "JPY",
                    "unit": 100,
                    "rate": {
                        "date": "2026-10-15",
                        "buying_rate": 2.9,
                        "selling_rate": 3.0,
                        "middle_rate": 2.95,
                    },
                },
            },
        )
    )
    rate = await fetch_myr_rate("JPY")
    assert rate.rate == Decimal("0.0295")


def test_fear_greed_and_feed_parsing() -> None:
    assert (
        parse_fear_greed({"data": [{"value": "63", "value_classification": "Greed"}]}).value == 63
    )
    with pytest.raises(ProviderError):
        parse_fear_greed({"data": [{"value": "300", "value_classification": "?"}]})
    rss = (
        b"<?xml version='1.0'?><rss><channel><title>Demo Wire</title>"
        b"<item><title>  Markets   steady </title></item><item><title></title></item></channel></rss>"
    )
    assert [(h.title, h.source) for h in parse_feed(rss, 5)] == [("Markets steady", "Demo Wire")]


def test_crypto_calendar_closes_at_midnight_utc() -> None:
    sessions = CryptoCalendar().closed_sessions(datetime(2026, 10, 16, 0, 5, tzinfo=UTC), 2)
    assert [s.day for s in sessions] == [date(2026, 10, 14), date(2026, 10, 15)]


def test_bursa_calendar_honours_configured_holidays() -> None:
    plain = calendar_for(Market.XKLS)
    overridden = calendar_for(Market.XKLS, frozenset({date(2026, 3, 20)}))
    assert plain.session(date(2026, 3, 20)) is not None
    assert overridden.session(date(2026, 3, 20)) is None


class StaticProvider:
    def __init__(self, name: str, bars: list, error: bool = False) -> None:  # type: ignore[type-arg]
        self.name = name
        self.bars = bars
        self.error = error

    async def fetch_daily(self, instrument: Instrument, start: date, end: date) -> ProviderBars:
        if self.error:
            raise ProviderError(self.name, "down", retryable=False)
        return ProviderBars(self.name, tuple(b for b in self.bars if start <= b.day <= end))


async def test_collector_cross_checks_recent_closes_and_falls_back_to_stored_bars() -> None:
    settings = load_settings()
    now = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
    days = [s.day for s in calendar_for(Market.XNYS).closed_sessions(now, 420)]
    primary = make_bars("AAPL", [200 + i * 0.1 for i in range(420)], days=days)
    secondary = [*primary[-5:-1], replace(primary[-1], close=primary[-1].close * Decimal("1.05"))]
    collector = Collector(
        settings,
        now,
        factories={
            "yahoo": lambda log: StaticProvider("yahoo", primary),
            "alphavantage": lambda log: StaticProvider("alphavantage", secondary),
        },
    )
    result = await collector.collect(AAPL)
    assert result.bars[-1].quality is BarQuality.DISPUTED
    assert result.bars[-2].quality is BarQuality.VERIFIED
    assert not result.readiness.ready

    down = Collector(
        settings,
        now,
        factories={
            "yahoo": lambda log: StaticProvider("yahoo", [], error=True),
            "alphavantage": lambda log: StaticProvider("alphavantage", secondary),
        },
    )
    fallback = await down.collect(AAPL, stored=primary[:-1])
    assert fallback.errors == ("yahoo: down",)
    assert fallback.bars[-1].day == days[-2]
    assert fallback.readiness.reasons[0].value == "provider_unavailable"
    assert calendar_gaps({"AAPL": fallback}) == {}


@pytest.mark.network
@pytest.mark.parametrize("symbol", ["BTC-USD", "BNB-USD", "SPY", "1155.KL"])
async def test_live_providers_still_parse(symbol: str) -> None:
    settings = load_settings()
    item = next(i for i in settings.instruments() if i.symbol == symbol)
    result = await Collector(settings, datetime.now(UTC)).collect(item)
    assert len(result.bars) >= 200
    assert not [e for e in result.errors if not e.startswith("alphavantage")]
