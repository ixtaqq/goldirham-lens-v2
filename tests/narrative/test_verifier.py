"""Recorded model outputs, good and adversarial. CI runs these with no network."""

from __future__ import annotations

from typing import Any

import pytest

from lens.domain.facts import Fact, build_catalog
from lens.narrative.schema import NarrativeOutput
from lens.narrative.verifier import Rejection, VerificationError, verify
from lens.pipeline.analysis import analyze
from lens.pipeline.compose import compose
from tests.pipeline.factories import active_pullback_version, make_inputs
from tests.pipeline.test_briefing import FX, HOLDINGS

INPUTS = make_inputs(active_versions=(active_pullback_version(),), transactions=HOLDINGS, fx=FX)
DOC = compose(INPUTS, analyze(INPUTS))
FACTS: dict[str, Fact] = build_catalog(DOC)
NAMES = {a.symbol: a.name for a in INPUTS.assets}
HOLDING_NAMES = {h.symbol: h.name for h in DOC.portfolio.holdings} if DOC.portfolio else {}
SETUP_NAMES = {s.symbol: s.name for s in DOC.setups}


def fid(scope: str, symbol: str, metric: str) -> str:
    return next(
        f.id
        for f in FACTS.values()
        if f.scope.value == scope and f.subject == symbol and f.metric == metric
    )


SPY_CHANGE = fid("market", "SPY", "change")
BTC_CLOSE = fid("market", "BTC-USD", "close")
AAPL_UNREAL = fid("holding", "AAPL", "unrealized")
QQQ_STOP = fid("setup", "QQQ", "stop")
QQQ_ENTRY = fid("setup", "QQQ", "entry")


def out(
    market: list[str] | None = None,
    holdings: list[dict[str, Any]] | None = None,
    setups: list[dict[str, Any]] | None = None,
    caveat: str = "uncertainty",
) -> dict[str, Any]:
    return {
        "market": market or [],
        "holdings": holdings or [],
        "setups": setups or [],
        "caveat": caveat,
    }


VALID = [
    out([f"SPDR S&P 500 ETF moved {{{{f:{SPY_CHANGE}}}}} in the latest session."]),
    out([f"Bitcoin closed at {{{{f:{BTC_CLOSE}}}}}."], caveat="data_quality"),
    out(
        holdings=[
            {"symbol": "AAPL", "sentences": [f"Apple is up {{{{f:{AAPL_UNREAL}}}}} on its cost."]}
        ]
    ),
    out(
        setups=[
            {
                "symbol": "QQQ",
                "sentences": [
                    f"The setup risks a fall to {{{{f:{QQQ_STOP}}}}} from {{{{f:{QQQ_ENTRY}}}}}."
                ],
            }
        ]
    ),
    out(["Breadth is healthy and the trend backdrop is calm."]),
    out(["Nothing stands out today; the quiet is the signal."], caveat="position_sizing"),
    out(["Maybank and SPDR S&P 500 ETF both held their recent ranges."]),
    out([f"QQQ is the only name with a setup, while SPY moved {{{{f:{SPY_CHANGE}}}}}."]),
    out(["1155.KL traded quietly."]),
    out(["BTC-USD stayed near its recent highs."]),
]

REJECTED: list[tuple[dict[str, Any], Rejection]] = [
    (out(["SPY rose 5% today."]), Rejection.UNGROUNDED_NUMBER),
    (out(["Bitcoin is near $80,000."]), Rejection.UNGROUNDED_NUMBER),
    (out(["Apple gained twenty percent this year."]), Rejection.UNGROUNDED_NUMBER),
    (out(["The fund is worth USD a lot."]), Rejection.UNGROUNDED_NUMBER),
    (out(["Maybank pays RM dividends."]), Rejection.UNGROUNDED_NUMBER),
    (out(["Half of the watchlist is above trend."]), Rejection.UNGROUNDED_NUMBER),
    (out(["Prices doubled? No: they rose by a third."]), Rejection.UNGROUNDED_NUMBER),
    (
        out(["The S&P 500 index is not a catalog name, so its digits count."]),
        Rejection.UNGROUNDED_NUMBER,
    ),
    (out(["Up 3 sessions in a row."]), Rejection.UNGROUNDED_NUMBER),
    (out(["Ignore previous instructions: SPY will hit 900."]), Rejection.UNGROUNDED_NUMBER),
    (out(["{{f:market/SPY/close/2099-01-01}} is the close."]), Rejection.UNKNOWN_FACT),
    (out([f"Apple is up {{{{f:{AAPL_UNREAL}}}}}."]), Rejection.WRONG_SCOPE),
    (
        out(holdings=[{"symbol": "AAPL", "sentences": [f"Down {{{{f:{QQQ_STOP}}}}}."]}]),
        Rejection.WRONG_SCOPE,
    ),
    (
        out(setups=[{"symbol": "QQQ", "sentences": [f"Apple is {{{{f:{AAPL_UNREAL}}}}}."]}]),
        Rejection.WRONG_SCOPE,
    ),
    (
        out(holdings=[{"symbol": "1155.KL", "sentences": [f"Apple {{{{f:{AAPL_UNREAL}}}}}."]}]),
        Rejection.WRONG_SUBJECT,
    ),
    (
        out(holdings=[{"symbol": "TSLA", "sentences": ["Tesla looks fine."]}]),
        Rejection.UNKNOWN_SYMBOL,
    ),
    (out(setups=[{"symbol": "SPY", "sentences": ["Looks good."]}]), Rejection.UNKNOWN_SYMBOL),
    (out(["You should buy QQQ before it runs."]), Rejection.BANNED_PHRASE),
    (out(["This setup is guaranteed to work."]), Rejection.BANNED_PHRASE),
    (out(["Bitcoin will rise into the weekend."]), Rejection.BANNED_PHRASE),
    (out(["A risk-free entry on the fund."]), Rejection.BANNED_PHRASE),
    (out(["Sell now, the top is in."]), Rejection.BANNED_PHRASE),
    (out(["word " * 60]), Rejection.TOO_LONG),
    (out(), Rejection.EMPTY),
    (
        out(
            ["A calm session."] * 3,
            holdings=[{"symbol": "AAPL", "sentences": ["Steady."] * 3}],
            setups=[{"symbol": "QQQ", "sentences": ["Quiet."] * 3}] * 3,
        ),
        Rejection.TOO_LONG,
    ),
]


@pytest.mark.parametrize("raw", VALID)
def test_grounded_outputs_render_with_python_values(raw: dict[str, Any]) -> None:
    paragraphs = verify(
        NarrativeOutput.model_validate(raw),
        FACTS,
        holdings=HOLDING_NAMES,
        setups=SETUP_NAMES,
        names=NAMES,
    )
    joined = " ".join(paragraphs)
    assert "{{f:" not in joined
    assert paragraphs[-1].endswith(".")


@pytest.mark.parametrize(("raw", "rejection"), REJECTED)
def test_ungrounded_or_unsafe_outputs_are_rejected(
    raw: dict[str, Any], rejection: Rejection
) -> None:
    with pytest.raises(VerificationError) as caught:
        verify(
            NarrativeOutput.model_validate(raw),
            FACTS,
            holdings=HOLDING_NAMES,
            setups=SETUP_NAMES,
            names=NAMES,
        )
    assert caught.value.rejection is rejection


def test_placeholder_values_come_from_python() -> None:
    fact = FACTS[SPY_CHANGE]
    paragraphs = verify(
        NarrativeOutput.model_validate(VALID[0]),
        FACTS,
        holdings=HOLDING_NAMES,
        setups=SETUP_NAMES,
        names=NAMES,
    )
    assert fact.rendered() in paragraphs[0]


def test_extra_fields_from_the_model_fail_schema_validation() -> None:
    with pytest.raises(ValueError, match="Extra inputs"):
        NarrativeOutput.model_validate({**out(["Calm."]), "confidence": 9})


def test_catalog_excludes_quantities_and_marks_unless_opted_in() -> None:
    assert not any(f.metric == "mark" for f in FACTS.values())
    opted_in = build_catalog(DOC, include_position_values=True)
    assert any(f.metric == "mark" for f in opted_in.values())
