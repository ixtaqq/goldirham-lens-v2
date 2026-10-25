"""Portfolio charts: server-rendered SVG from stored briefing totals, no script, no inline style."""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

from lens.dashboard import pages
from lens.dashboard.queries import PortfolioPoint

START = date(2026, 10, 12)


def _points() -> list[PortfolioPoint]:
    rows = [
        ("1000", {"stock": "60.0", "crypto": "40.0"}),
        ("1100", {"stock": "55.0", "crypto": "45.0"}),
        ("1050.5", {"stock": "50.0", "etf": "20.0", "crypto": "30.0"}),
    ]
    return [
        PortfolioPoint(
            START + timedelta(days=i),
            Decimal(total),
            "MYR",
            {k: Decimal(v) for k, v in exposure.items()},
        )
        for i, (total, exposure) in enumerate(rows)
    ]


def test_the_portfolio_page_draws_equity_and_exposure_with_labels() -> None:
    html = pages.portfolio(_points())

    assert html.count("<svg") == 2
    assert (
        "aria-label='Portfolio value in MYR by briefing date, 12 Oct 2026 to 14 Oct 2026'" in html
    )
    assert "aria-label='Exposure by asset class, percent of the valued portfolio" in html
    assert ">MYR 1,100.00<" in html
    assert ">MYR 1,000.00<" in html
    assert "<title>13 Oct 2026: MYR 1,100.00</title>" in html
    assert "<title>14 Oct 2026, crypto: 30.0%</title>" in html
    assert ">MYR 1,050.50<" in html


def test_series_colours_follow_the_asset_class_not_its_rank() -> None:
    html = pages.portfolio(_points())
    legend = re.findall(r"<li><span class='swatch (s-\d)'></span>(\w+)</li>", html)
    assert legend == [("s-1", "stock"), ("s-2", "etf"), ("s-3", "crypto")]
    only_crypto = [
        PortfolioPoint(p.day, p.total, p.currency, {"crypto": Decimal(100)}) for p in _points()
    ]
    alone = pages.portfolio(only_crypto)
    assert "class='line s-3'" in alone
    assert "class='legend'" not in alone


def test_charts_need_two_points_and_never_use_inline_style() -> None:
    one = pages.portfolio(_points()[:1])
    assert "<svg" not in one
    assert "MYR 1,000.00" in one
    assert " style=" not in pages.portfolio(_points())


def test_end_labels_that_would_overlap_are_pushed_apart() -> None:
    days = [START, START + timedelta(days=1)]
    html = pages.line_chart(
        [
            ("stock", "s-1", [(days[0], Decimal(40)), (days[1], Decimal("50.0"))]),
            ("crypto", "s-3", [(days[0], Decimal(60)), (days[1], Decimal("50.5"))]),
        ],
        label="test",
        value=lambda v: f"{v:.1f}%",
        low=Decimal(0),
        high=Decimal(100),
    )
    ys = [float(y) for y in re.findall(r"<text class='label' x='[\d.]+' y='([\d.]+)'>", html)]
    assert len(ys) == 2
    assert abs(ys[0] - ys[1]) >= 14
