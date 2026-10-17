from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum

from lens.domain.reasons import ReasonCode


class BarQuality(StrEnum):
    VERIFIED = "verified"
    SINGLE_SOURCE = "single_source"
    DISPUTED = "disputed"
    SUSPECT = "suspect"
    INVALID = "invalid"
    CORPORATE_ACTION_PENDING = "corporate_action_pending"


USABLE_QUALITIES = frozenset({BarQuality.VERIFIED, BarQuality.SINGLE_SOURCE})

QUALITY_REASON: dict[BarQuality, ReasonCode] = {
    BarQuality.DISPUTED: ReasonCode.DISPUTED_BAR,
    BarQuality.SUSPECT: ReasonCode.SUSPECT_BAR,
    BarQuality.INVALID: ReasonCode.INVALID_BAR,
    BarQuality.CORPORATE_ACTION_PENDING: ReasonCode.CORPORATE_ACTION_PENDING,
    BarQuality.SINGLE_SOURCE: ReasonCode.SINGLE_SOURCE_UNVERIFIED,
}


@dataclass(frozen=True, slots=True)
class Bar:
    """One completed daily session for one instrument."""

    symbol: str
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    provider: str
    quality: BarQuality = BarQuality.VERIFIED
    reasons: tuple[ReasonCode, ...] = field(default=())

    @property
    def usable(self) -> bool:
        return self.quality in USABLE_QUALITIES

    def with_quality(self, quality: BarQuality, *reasons: ReasonCode) -> Bar:
        return replace(self, quality=quality, reasons=tuple(dict.fromkeys(self.reasons + reasons)))
