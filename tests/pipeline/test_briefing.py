"""Golden-file briefings for the scenarios in the build spec, plus rendering invariants."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from syrupy.assertion import SnapshotAssertion

from lens.delivery.chunker import chunk
from lens.delivery.renderer import TELEGRAM_LIMIT, render_sections
from lens.domain.bars import BarQuality
from lens.domain.briefing import Headline
from lens.domain.evaluation import SignalStatus
from lens.domain.holdings import ReviewAction
from lens.domain.instruments import AssetClass
from lens.pipeline.analysis import analyze
from lens.pipeline.compose import compose
from lens.pipeline.inputs import ContextIn, CycleInputs, FxIn, SignalIn, pack, unpack
from tests.pipeline.factories import (
    active_pullback_version,
    asset,
    make_inputs,
    standard_assets,
    tx,
)

FX = (FxIn(quote="USD", base="MYR", rate=Decimal("4.4210"), day=date(2026, 10, 15), source="bnm"),)
HOLDINGS = (
    tx(1, "AAPL", "BUY", "2026-06-01", "USD", quantity="20", price="110", fee="1"),
    tx(2, "1155.KL", "BUY", "2026-03-02", "MYR", quantity="1000", price="9.20", fee="12"),
)


def _text(inputs: CycleInputs) -> str:
    return "\n\n".join(render_sections(compose(inputs, analyze(inputs))))


def test_quiet_day_with_no_live_strategy(snapshot: SnapshotAssertion) -> None:
    """Scenario 4: no setups is said once, and the inactive strategy is named."""
    text = _text(make_inputs())
    assert "No new setups today." in text
    assert "strategy has no backtest report yet" in text
    assert text == snapshot


def test_live_strategy_with_holdings_and_fx(snapshot: SnapshotAssertion) -> None:
    inputs = make_inputs(active_versions=(active_pullback_version(),), transactions=HOLDINGS, fx=FX)
    doc = compose(inputs, analyze(inputs))
    assert [s.symbol for s in doc.setups] == ["QQQ"]
    assert doc.portfolio is not None
    assert doc.portfolio.excluded_from_total == ()
    assert "\n\n".join(render_sections(doc)) == snapshot


def test_holding_without_fx_is_shown_and_excluded(snapshot: SnapshotAssertion) -> None:
    """Scenario 9."""
    text = _text(make_inputs(transactions=HOLDINGS))
    assert "Not in total (no price or FX rate): AAPL" in text
    assert text == snapshot


def test_disputed_latest_close_marks_the_previous_verified_close() -> None:
    """Scenario 3 for holdings: the mark is the last verified close, labelled disputed."""
    assets = [a for a in standard_assets() if a.symbol != "AAPL"]
    assets.append(
        asset(
            "AAPL",
            AssetClass.STOCK,
            [100.0 * 1.002**i for i in range(260)],
            name="Apple",
            last_quality=BarQuality.DISPUTED,
        )
    )
    inputs = make_inputs(assets=tuple(assets), transactions=HOLDINGS, fx=FX)
    doc = compose(inputs, analyze(inputs))
    assert doc.portfolio is not None
    line = next(h for h in doc.portfolio.holdings if h.symbol == "AAPL")
    aapl = inputs.asset("AAPL")
    assert aapl is not None
    assert line.mark == aapl.bars[-2].c
    assert line.mark_day == aapl.bars[-2].day
    assert line.mark_status.value == "disputed"
    assert "latest close disputed" in "\n".join(render_sections(doc))


def test_exit_review_is_listed_first_with_its_reason(snapshot: SnapshotAssertion) -> None:
    falling = [100.0 * 1.002**i for i in range(240)] + [100.0 * 0.92**i for i in range(1, 21)]
    assets = [a for a in standard_assets() if a.symbol != "AAPL"]
    assets.append(asset("AAPL", AssetClass.STOCK, falling, name="Apple"))
    inputs = make_inputs(
        assets=tuple(assets),
        transactions=HOLDINGS,
        fx=FX,
        previous_reviews={"AAPL": ReviewAction.HOLD},
    )
    doc = compose(inputs, analyze(inputs))
    assert doc.portfolio is not None
    assert doc.portfolio.holdings[0].symbol == "AAPL"
    assert doc.portfolio.holdings[0].review is ReviewAction.EXIT
    text = "\n\n".join(render_sections(doc))
    assert "AAPL review HOLD → EXIT" in text
    assert text == snapshot


def test_degraded_briefing(snapshot: SnapshotAssertion) -> None:
    inputs = make_inputs(
        mode="degraded",
        degraded_reason="The database was unreachable.",
        sources_unavailable=("database",),
        context=ContextIn(),
    )
    text = _text(inputs)
    assert "<b>Degraded briefing.</b>" in text
    assert text == snapshot


def test_signal_events_are_reported() -> None:
    qqq = make_inputs().asset("QQQ")
    assert qqq is not None
    last = qqq.bars[-1]
    signal = SignalIn(
        id=7,
        symbol="QQQ",
        strategy="pullback_in_uptrend",
        signal_day=qqq.bars[-10].day,
        expiry_days=120,
        entry=last.c * Decimal("1.2"),
        stop=last.c * Decimal("1.1"),
        t1=last.c * Decimal("1.4"),
        t2=last.c * Decimal("1.6"),
        status=SignalStatus.OPEN,
        last_evaluated=None,
        t1_touched_on=None,
        mfe_r=Decimal(0),
        mae_r=Decimal(0),
        last_close=None,
    )
    doc = compose(make_inputs(signals=(signal,)), analyze(make_inputs(signals=(signal,))))
    assert [(s.symbol, s.event.value) for s in doc.open_signals] == [("QQQ", "STOPPED")]


def test_every_dynamic_string_is_escaped() -> None:
    hostile = ContextIn(
        headlines=(Headline(title="<script>alert(1)</script> & co", source="<b>x</b>"),)
    )
    text = _text(make_inputs(context=hostile))
    assert "<script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in text
    assert "&lt;b&gt;x&lt;/b&gt;" in text


@pytest.mark.parametrize("width", [200, 1000, TELEGRAM_LIMIT])
def test_chunks_respect_the_limit_and_keep_tags_balanced(width: int) -> None:
    inputs = make_inputs(active_versions=(active_pullback_version(),), transactions=HOLDINGS, fx=FX)
    chunks = chunk(render_sections(compose(inputs, analyze(inputs))), width)
    assert all(len(c) <= width for c in chunks)
    for text in chunks:
        for tag in ("b", "i", "code"):
            assert text.count(f"<{tag}>") == text.count(f"</{tag}>")


def test_inputs_round_trip_through_packing() -> None:
    inputs = make_inputs(transactions=HOLDINGS, fx=FX)
    assert unpack(pack(inputs)) == inputs
