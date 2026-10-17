from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class AssetClass(StrEnum):
    CRYPTO = "crypto"
    STOCK = "stock"
    ETF = "etf"


class Market(StrEnum):
    XNYS = "XNYS"
    XKLS = "XKLS"
    CRYPTO_UTC = "CRYPTO_UTC"


class UnsupportedMarketError(ValueError):
    pass


_US_SYMBOL = re.compile(r"[A-Z]{1,5}(?:[.-][A-Z])?")
_BURSA_SYMBOL = re.compile(r"[0-9A-Z]{4}\.KL")
_CRYPTO_SYMBOL = re.compile(r"[A-Z0-9]{2,10}-USD")
_INDEX_SYMBOL = re.compile(r"\^[A-Z]{2,8}")


def market_for(symbol: str, asset_class: AssetClass) -> tuple[Market, str]:
    """Return the market and quote currency for a supported symbol."""
    if asset_class is AssetClass.CRYPTO:
        if _CRYPTO_SYMBOL.fullmatch(symbol):
            return Market.CRYPTO_UTC, "USD"
    elif _BURSA_SYMBOL.fullmatch(symbol) or symbol == "^KLSE":
        return Market.XKLS, "MYR"
    elif _US_SYMBOL.fullmatch(symbol) or _INDEX_SYMBOL.fullmatch(symbol):
        return Market.XNYS, "USD"
    raise UnsupportedMarketError(f"unsupported market for {symbol} ({asset_class})")


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    name: str
    asset_class: AssetClass
    market: Market
    currency: str

    @classmethod
    def create(cls, symbol: str, asset_class: AssetClass, name: str | None = None) -> Instrument:
        normalized = symbol.strip().upper()
        market, currency = market_for(normalized, asset_class)
        return cls(normalized, name or normalized, asset_class, market, currency)
