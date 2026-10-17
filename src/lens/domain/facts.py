"""The fact catalog: every number the narrative may reference, built from the document itself."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from lens.domain.briefing import BriefingDocument


class FactScope(StrEnum):
    MARKET = "market"
    HOLDING = "holding"
    SETUP = "setup"


@dataclass(frozen=True, slots=True)
class Fact:
    id: str
    scope: FactScope
    subject: str
    metric: str
    value: Decimal
    unit: str
    session: date
    source: str

    def rendered(self) -> str:
        """The value as the reader sees it, with unit and session."""
        if self.unit == "%chg":
            text = f"{self.value:+.1f}%"
        elif self.unit == "%":
            text = f"{self.value:.1f}%"
        elif self.unit == "pts":
            text = f"{self.value:.0f}"
        else:
            text = (
                f"{self.unit} {self.value:,.2f}"
                if abs(self.value) >= 1
                else f"{self.unit} {self.value:.4f}"
            )
        return f"{text} ({self.session:%d %b})"


def _add(
    catalog: dict[str, Fact],
    scope: FactScope,
    subject: str,
    metric: str,
    value: Decimal | None,
    unit: str,
    session: date | None,
    source: str,
) -> None:
    if value is None or session is None or not value.is_finite():
        return
    fact_id = f"{scope}/{subject}/{metric}/{session.isoformat()}"
    catalog[fact_id] = Fact(fact_id, scope, subject, metric, value, unit, session, source)


def build_catalog(
    doc: BriefingDocument, *, include_position_values: bool = False
) -> dict[str, Fact]:
    catalog: dict[str, Fact] = {}
    for bench in doc.market.benchmarks:
        _add(
            catalog,
            FactScope.MARKET,
            bench.symbol,
            "close",
            bench.close,
            bench.currency,
            bench.session,
            "verified close",
        )
        _add(
            catalog,
            FactScope.MARKET,
            bench.symbol,
            "change",
            bench.change_pct,
            "%chg",
            bench.session,
            "verified close",
        )
    if doc.market.breadth_pct is not None:
        session = max((d.session for d in doc.data_as_of if d.session), default=None)
        _add(
            catalog,
            FactScope.MARKET,
            "watchlist",
            "breadth_above_ma200",
            doc.market.breadth_pct,
            "%",
            session,
            "computed",
        )
    if doc.portfolio is not None:
        for line in doc.portfolio.holdings:
            _add(
                catalog,
                FactScope.HOLDING,
                line.symbol,
                "day_change",
                line.day_change_pct,
                "%chg",
                line.mark_day,
                line.mark_source or "",
            )
            _add(
                catalog,
                FactScope.HOLDING,
                line.symbol,
                "unrealized",
                line.unrealized_pct,
                "%chg",
                line.mark_day,
                line.mark_source or "",
            )
            if include_position_values:
                _add(
                    catalog,
                    FactScope.HOLDING,
                    line.symbol,
                    "mark",
                    line.mark,
                    line.currency,
                    line.mark_day,
                    line.mark_source or "",
                )
    for setup in doc.setups:
        for metric, value in (
            ("entry", setup.entry),
            ("stop", setup.stop),
            ("t1", setup.t1),
            ("t2", setup.t2),
        ):
            _add(
                catalog,
                FactScope.SETUP,
                setup.symbol,
                metric,
                value,
                setup.currency,
                setup.session,
                "deterministic setup",
            )
        _add(
            catalog,
            FactScope.SETUP,
            setup.symbol,
            "size",
            setup.size_pct,
            "%",
            setup.session,
            "deterministic setup",
        )
    return catalog
