"""Walk-forward research over the seeded synthetic market: no network, no database."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from lens.backtest.engine import AssetHistory
from lens.backtest.research import fold_windows, parameter_grid, walk_forward
from lens.demo import demo_settings, generate_market
from lens.domain.strategy.base import RiskInputs
from lens.settings import load_settings

SETTINGS = demo_settings(load_settings())
BASE = dict(SETTINGS.strategies["pullback_in_uptrend"].params)
RISK = RiskInputs(Decimal(1), Decimal(20))
HISTORIES = [
    AssetHistory(a.instrument, a.bars, SETTINGS.tick_rule(a.instrument.market))
    for a in generate_market(SETTINGS)
][:3]
START, END = date(2023, 5, 5), date(2026, 10, 15)


def _candidates() -> list:  # type: ignore[type-arg]
    return parameter_grid("pullback_in_uptrend", BASE, {"rsi_trigger": ["25", "40"]})


def test_the_grid_is_every_combination_with_its_own_version() -> None:
    grid = parameter_grid(
        "pullback_in_uptrend",
        BASE,
        {"rsi_trigger": ["20", "30"], "atr_stop_multiple": ["1.5", "2.5"]},
    )
    assert len(grid) == 4
    assert len({c.version for c in grid}) == 4
    assert {(c.params.rsi_trigger, c.params.atr_stop_multiple) for c in grid} == {
        (Decimal(r), Decimal(a)) for r in ("20", "30") for a in ("1.5", "2.5")
    }


def test_the_grid_refuses_a_parameter_the_strategy_does_not_have() -> None:
    with pytest.raises(ValueError, match="not a parameter"):
        parameter_grid("pullback_in_uptrend", BASE, {"moon_phase": ["full"]})


def test_folds_train_on_everything_before_each_unseen_test_window() -> None:
    windows = fold_windows(START, END, folds=3)
    assert len(windows) == 3
    for (train_start, train_end, test_start, test_end), following in zip(
        windows, [*windows[1:], None], strict=True
    ):
        assert train_start == START
        assert train_end < test_start <= test_end
        if following is not None:
            assert following[2] > test_end
    assert windows[-1][3] == END


def test_walk_forward_picks_on_training_data_and_scores_the_next_window() -> None:
    report = walk_forward(
        HISTORIES,
        _candidates(),
        RISK,
        start=START,
        end=END,
        folds=3,
        min_trades=3,
        baseline_runs=20,
    )
    body = report.body
    assert body["strategy"] == "pullback_in_uptrend"
    assert len(body["folds"]) == 3
    versions = {c["version"] for c in body["candidates"]}
    for fold in body["folds"]:
        assert fold["chosen"] is None or fold["chosen"] in versions
        assert {s["version"] for s in fold["scores"]} == versions
        for trade in fold["test_trades"]:
            assert fold["test"][0] <= trade["signal_day"] <= fold["test"][1]
    assert body["verdict"] in ("beats_random", "does_not_beat_random", "inconclusive")
    assert "## Verdict" in report.markdown
    again = walk_forward(
        HISTORIES,
        _candidates(),
        RISK,
        start=START,
        end=END,
        folds=3,
        min_trades=3,
        baseline_runs=20,
    )
    assert again.report_hash == report.report_hash


def test_training_scores_never_see_bars_after_the_training_window() -> None:
    windows = fold_windows(START, END, folds=3)
    train_end = windows[0][1]
    shocked = [
        replace(
            h,
            bars=tuple(
                b if b.day <= train_end else replace(b, low=b.low / 2, close=b.close / 2)
                for b in h.bars
            ),
        )
        for h in HISTORIES
    ]
    kwargs = {"start": START, "end": END, "folds": 3, "min_trades": 3, "baseline_runs": 5}
    plain = walk_forward(HISTORIES, _candidates(), RISK, **kwargs)  # type: ignore[arg-type]
    shaken = walk_forward(shocked, _candidates(), RISK, **kwargs)  # type: ignore[arg-type]
    assert plain.body["folds"][0]["scores"] == shaken.body["folds"][0]["scores"]
    assert plain.body["folds"][0]["chosen"] == shaken.body["folds"][0]["chosen"]
