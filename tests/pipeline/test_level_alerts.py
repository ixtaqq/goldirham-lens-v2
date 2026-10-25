"""Level alerts inside the briefing: analysis finds the crossing, compose and render show it."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from lens.delivery.renderer import render_sections
from lens.pipeline.analysis import analyze
from lens.pipeline.compose import compose
from lens.pipeline.cycle import render
from lens.pipeline.inputs import LevelAlertIn, pack, unpack
from tests.pipeline.factories import make_inputs


def _alerts() -> tuple[LevelAlertIn, ...]:
    return (
        LevelAlertIn(
            id=1, symbol="SPY", direction="above", level=Decimal("600"), created_on=date(2026, 1, 2)
        ),
        LevelAlertIn(
            id=2, symbol="AAPL", direction="below", level=Decimal("50"), created_on=date(2026, 1, 2)
        ),
        LevelAlertIn(
            id=3, symbol="TSLA", direction="above", level=Decimal("1"), created_on=date(2026, 1, 2)
        ),
    )


def test_a_crossed_level_is_reported_once_with_its_session() -> None:
    inputs = make_inputs(level_alerts=_alerts())
    analysis = analyze(inputs)

    assert [h.alert.id for h in analysis.alert_hits] == [1]
    hit = analysis.alert_hits[0]
    assert hit.close >= Decimal(600)

    doc = compose(inputs, analysis)
    (line,) = doc.level_alerts
    assert (line.symbol, line.direction, line.level, line.day) == (
        "SPY",
        "above",
        Decimal("600"),
        hit.day,
    )
    text = "\n\n".join(render_sections(doc))
    assert "<b>Price alerts</b>" in text
    assert f"• SPY closed at USD {hit.close:,.2f}" in text
    assert "above your USD 600.00 level" in text


def test_without_alerts_nothing_is_added_or_stored() -> None:
    inputs = make_inputs()
    _, document = render(inputs)
    assert "level_alerts" not in document
    assert "Price alerts" not in "\n\n".join(render_sections(compose(inputs, analyze(inputs))))


def test_alerts_survive_packing_for_replay() -> None:
    inputs = make_inputs(level_alerts=_alerts())
    assert unpack(pack(inputs)) == inputs
