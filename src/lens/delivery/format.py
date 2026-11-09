"""One place for how numbers look. Every renderer uses these."""

from __future__ import annotations

import html
from datetime import date
from decimal import Decimal

from lens.domain.instruments import Market

MARKET_LABELS = {Market.XNYS: "US", Market.XKLS: "Bursa", Market.CRYPTO_UTC: "Crypto (UTC)"}


def esc(text: object) -> str:
    return html.escape(str(text), quote=False)


def amount(value: Decimal) -> str:
    magnitude = abs(value)
    places = 2 if magnitude >= 1 else 4 if magnitude >= Decimal("0.01") else 6
    return f"{value:,.{places}f}"


def price(value: Decimal, currency: str) -> str:
    return f"{currency} {amount(value)}"


def move(value: Decimal) -> str:
    """A day's change as an arrow and its size: ▲0.3%, ▼1.2%, ▬0.0% when it rounds to nothing."""
    size = f"{abs(value):.1f}"
    arrow = "▬" if size == "0.0" else "▲" if value > 0 else "▼"
    return f"{arrow}{size}%"


def money(value: Decimal, currency: str) -> str:
    return f"{currency} {value:,.2f}"


def signed_pct(value: Decimal) -> str:
    return f"{value:+.1f}%".replace("-", "−")


def pct(value: Decimal) -> str:
    return f"{value:.1f}%"


def r_multiple(value: Decimal) -> str:
    return f"{value:+.2f}R".replace("-", "−")


def short_day(day: date) -> str:
    return f"{day.day} {day:%b}"


def long_day(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b %Y}"
