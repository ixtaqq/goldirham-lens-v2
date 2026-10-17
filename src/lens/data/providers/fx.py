"""Dated FX rates into MYR. Primary: Bank Negara Malaysia Open API. Fallback: ECB via Frankfurter."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from lens.data.providers.base import (
    CallLog,
    ProviderError,
    http_client,
    raise_for_status,
    with_retries,
)
from lens.domain.money import NonFiniteNumberError, to_decimal
from lens.domain.portfolio import FxRate

BNM_URL = "https://api.bnm.gov.my/public/exchange-rate/{currency}"
BNM_ACCEPT = "application/vnd.BNM.API.v1+json"
FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"


def parse_bnm(currency: str, payload: Any) -> FxRate:
    try:
        data = payload["data"]
        rate = data["rate"]
        unit = to_decimal(data.get("unit", 1))
        middle = to_decimal(rate["middle_rate"])
        return FxRate(currency, "MYR", middle / unit, date.fromisoformat(rate["date"]), "bnm")
    except (KeyError, TypeError, ValueError, NonFiniteNumberError) as error:
        raise ProviderError("bnm", "unexpected payload", retryable=False) from error


def parse_frankfurter(currency: str, payload: Any) -> FxRate:
    try:
        rate = to_decimal(payload["rates"]["MYR"]) / to_decimal(payload.get("amount", 1))
        return FxRate(currency, "MYR", rate, date.fromisoformat(payload["date"]), "ecb")
    except (KeyError, TypeError, ValueError, NonFiniteNumberError) as error:
        raise ProviderError("frankfurter", "unexpected payload", retryable=False) from error


async def fetch_myr_rate(
    currency: str, client: httpx.AsyncClient | None = None, log: CallLog | None = None
) -> FxRate:
    """Latest published rate for one MYR per `currency`, trying BNM first."""
    own = client is None
    http = client or http_client()
    try:

        async def bnm() -> FxRate:
            response = await http.get(
                BNM_URL.format(currency=currency), headers={"Accept": BNM_ACCEPT}
            )
            raise_for_status("bnm", response)
            return parse_bnm(currency, response.json())

        async def ecb() -> FxRate:
            response = await http.get(FRANKFURTER_URL, params={"base": currency, "symbols": "MYR"})
            raise_for_status("frankfurter", response)
            return parse_frankfurter(currency, response.json())

        try:
            return await with_retries("bnm", bnm, log, attempts=2)
        except ProviderError:
            return await with_retries("frankfurter", ecb, log, attempts=2)
    finally:
        if own:
            await http.aclose()
