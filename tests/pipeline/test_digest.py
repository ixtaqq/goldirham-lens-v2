"""The weekly digest: part of one briefing a week, computed from that briefing's own inputs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from syrupy.assertion import SnapshotAssertion

from lens.delivery.renderer import render_sections
from lens.domain.instruments import AssetClass
from lens.pipeline.analysis import analyze
from lens.pipeline.compose import compose
from lens.pipeline.cycle import render
from lens.pipeline.inputs import CycleInputs
from lens.settings import load_settings
from tests.pipeline.factories import asset, make_inputs, standard_assets
from tests.pipeline.test_briefing import FX, HOLDINGS

SUNDAY = date(2026, 10, 18)


def _settings(**digest: Any) -> dict[str, Any]:
    raw = load_settings().model_dump(mode="json")
    raw["digest"] = raw["digest"] | digest
    return raw


def _sunday(**overrides: Any) -> CycleInputs:
    return make_inputs(briefing_date=SUNDAY, transactions=HOLDINGS, fx=FX, **overrides)


def _movers() -> tuple[Any, ...]:
    flat = [100.0] * 255
    return (
        *standard_assets(),
        asset("MSFT", AssetClass.STOCK, [*flat, 100, 102, 104, 108, 110], name="Microsoft"),
        asset("5183.KL", AssetClass.STOCK, [*flat, 100, 99, 97, 96, 95], name="Petronas Chemicals"),
    )


def test_the_configured_weekday_briefing_carries_the_week() -> None:
    inputs = _sunday(assets=_movers())
    doc = compose(inputs, analyze(inputs))

    assert doc.week is not None
    spy = next(line for line in doc.week.benchmarks if line.symbol == "SPY")
    assert (spy.from_day, spy.to_day) == (date(2026, 10, 8), date(2026, 10, 15))
    assert spy.change_pct == Decimal("0.50")
    msft = doc.week.gainers[0]
    assert msft.symbol == "MSFT"
    assert msft.change_pct == Decimal("10.00")
    assert [line.symbol for line in doc.week.decliners] == ["QQQ", "5183.KL"]
    assert {line.symbol for line in doc.week.holdings} == {"AAPL", "1155.KL"}

    text = "\n\n".join(render_sections(doc))
    assert "<b>This week</b> · 8 Oct to 15 Oct" in text
    assert "MSFT +10.0%" in text
    assert "5183.KL −5.0%" in text


def test_other_days_have_no_week_and_store_no_week_key() -> None:
    inputs = make_inputs()
    _, document = render(inputs)
    assert compose(inputs, analyze(inputs)).week is None
    assert "week" not in document


def test_a_switched_off_digest_or_settings_from_before_it_add_nothing() -> None:
    off = _sunday(settings=_settings(enabled=False))
    assert compose(off, analyze(off)).week is None

    before = load_settings().model_dump(mode="json")
    del before["digest"]
    old = _sunday(settings=before)
    _, document = render(old)
    assert "week" not in document


def test_sunday_briefing_golden(snapshot: SnapshotAssertion) -> None:
    inputs = _sunday(assets=_movers())
    assert "\n\n".join(render_sections(compose(inputs, analyze(inputs)))) == snapshot
