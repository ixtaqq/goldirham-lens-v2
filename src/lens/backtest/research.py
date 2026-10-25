"""Walk-forward research: sweep parameters, choose on past data, score on the next unseen window.

Each fold trains on every session from the start up to the fold's test window (anchored) and
sees only bars up to the end of its training window, so a trade still open there cannot borrow
its outcome from the future. The chosen parameters then trade the test window. All test windows
together are the out-of-sample result, compared with random entries on the same windows.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from lens.backtest.engine import (
    ASSUMPTIONS,
    AssetHistory,
    Trade,
    run_random_baseline,
    run_strategy,
)
from lens.backtest.report import CAVEATS, summarize
from lens.domain.strategy.base import RiskInputs
from lens.domain.strategy.registry import ConfiguredStrategy, configure

TEST_SHARE = Decimal("0.5")
MIN_OUT_OF_SAMPLE = 20
RESEARCH_CAVEATS = (
    *CAVEATS,
    "Every candidate tried raises the chance one looks good by luck; only the walk-forward "
    "result counts, and a wider sweep needs a stronger result.",
)

Window = tuple[date, date, date, date]


def parameter_grid(
    strategy: str, base: Mapping[str, Any], sweep: Mapping[str, Sequence[Any]]
) -> list[ConfiguredStrategy]:
    """Every combination of the swept values over `base`, one configured strategy each."""
    unknown = sorted(set(sweep) - set(base))
    if unknown:
        raise ValueError(f"{', '.join(unknown)} is not a parameter of {strategy}")
    keys = list(sweep)
    candidates: dict[str, ConfiguredStrategy] = {}
    for values in itertools.product(*(sweep[k] for k in keys)):
        params = dict(base) | dict(zip(keys, values, strict=True))
        (configured,) = configure({strategy: (True, params)})
        candidates.setdefault(configured.version, configured)
    return list(candidates.values())


def fold_windows(start: date, end: date, *, folds: int) -> list[Window]:
    """(train start, train end, test start, test end) per fold; tests tile the last half."""
    if folds < 1:
        raise ValueError("folds must be at least 1")
    span = (end - start).days
    first_test = start + timedelta(days=int(span * (1 - TEST_SHARE)))
    length = (end - first_test).days // folds
    windows = []
    for index in range(folds):
        test_start = first_test + timedelta(days=index * length)
        test_end = end if index == folds - 1 else test_start + timedelta(days=length - 1)
        windows.append((start, test_start - timedelta(days=1), test_start, test_end))
    return windows


def _until(histories: Sequence[AssetHistory], end: date) -> list[AssetHistory]:
    cut = [replace(h, bars=tuple(b for b in h.bars if b.day <= end)) for h in histories]
    return [h for h in cut if h.bars]


@dataclass(frozen=True, slots=True)
class ResearchReport:
    body: dict[str, Any]
    report_hash: str
    markdown: str


def _trade_row(trade: Trade) -> dict[str, Any]:
    return {
        "symbol": trade.symbol,
        "signal_day": trade.signal_day.isoformat(),
        "exit_day": trade.exit_day.isoformat() if trade.exit_day else None,
        "status": trade.status.value,
        "outcome_r": None
        if trade.outcome_r is None
        else str(trade.outcome_r.quantize(Decimal("0.01"))),
    }


def walk_forward(
    histories: Sequence[AssetHistory],
    candidates: Sequence[ConfiguredStrategy],
    risk: RiskInputs,
    *,
    start: date,
    end: date,
    folds: int = 3,
    min_trades: int = 10,
    min_sessions: int = 200,
    baseline_runs: int = 200,
) -> ResearchReport:
    if not candidates:
        raise ValueError("no candidates to research")
    by_version = {c.version: c for c in candidates}
    fold_rows: list[dict[str, Any]] = []
    out_of_sample: list[Trade] = []
    baseline_by_run: dict[int, list[tuple[Decimal, int]]] = {}
    for train_start, train_end, test_start, test_end in fold_windows(start, end, folds=folds):
        seen = _until(histories, train_end)
        scores = []
        for candidate in candidates:
            summary = summarize(
                run_strategy(
                    seen,
                    candidate,
                    risk,
                    start=train_start,
                    end=train_end,
                    min_sessions=min_sessions,
                )
            )
            scores.append(
                {
                    "version": candidate.version,
                    "resolved": summary["resolved"],
                    "expectancy_r": summary.get("expectancy_r"),
                }
            )
        eligible = [s for s in scores if s["resolved"] >= min_trades]
        best = max(eligible, key=lambda s: Decimal(s["expectancy_r"]), default=None)
        chosen = by_version[best["version"]] if best is not None else None
        test_trades: list[Trade] = []
        if chosen is not None:
            test_trades = run_strategy(
                histories, chosen, risk, start=test_start, end=test_end, min_sessions=min_sessions
            )
            per_asset: dict[str, int] = {}
            for trade in test_trades:
                per_asset[trade.symbol] = per_asset.get(trade.symbol, 0) + 1
            means = run_random_baseline(
                histories,
                chosen,
                risk,
                start=test_start,
                end=test_end,
                trades_per_asset=per_asset,
                runs=baseline_runs,
                min_sessions=min_sessions,
            )
            for run, mean in enumerate(means):
                baseline_by_run.setdefault(run, []).append((mean, len(test_trades)))
        out_of_sample += test_trades
        fold_rows.append(
            {
                "train": [train_start.isoformat(), train_end.isoformat()],
                "test": [test_start.isoformat(), test_end.isoformat()],
                "scores": scores,
                "chosen": chosen.version if chosen else None,
                "test_trades": [_trade_row(t) for t in sorted(test_trades, key=_order)],
            }
        )

    combined = sorted(
        sum((m * n for m, n in parts), Decimal(0)) / sum(n for _, n in parts)
        for parts in baseline_by_run.values()
        if sum(n for _, n in parts)
    )
    baseline: dict[str, Any] | None = None
    if combined:
        baseline = {
            "runs": len(combined),
            "mean_expectancy_r": str(
                (sum(combined, Decimal(0)) / len(combined)).quantize(Decimal("0.01"))
            ),
            "p95_r": str(combined[max(0, int(0.95 * len(combined)) - 1)].quantize(Decimal("0.01"))),
        }
    full = summarize(out_of_sample)
    verdict = "inconclusive"
    if full["resolved"] >= MIN_OUT_OF_SAMPLE and baseline is not None:
        beats = Decimal(full["expectancy_r"]) > Decimal(baseline["p95_r"])
        verdict = "beats_random" if beats else "does_not_beat_random"
    last_choice = next((f["chosen"] for f in reversed(fold_rows) if f["chosen"]), None)
    first = candidates[0]
    body: dict[str, Any] = {
        "strategy": first.name,
        "period": [start.isoformat(), end.isoformat()],
        "folds": fold_rows,
        "min_trades": min_trades,
        "candidates": [
            {"version": c.version, "params": c.params.model_dump(mode="json")} for c in candidates
        ],
        "assets": sorted(h.instrument.symbol for h in histories),
        "out_of_sample": {
            "full_to_t2": full,
            "half_at_t1_breakeven": summarize(out_of_sample, scaled=True),
        },
        "random_entry_baseline": baseline,
        "verdict": verdict,
        "latest_choice": last_choice,
        "assumptions": list(ASSUMPTIONS),
        "caveats": list(RESEARCH_CAVEATS),
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return ResearchReport(body, digest, to_markdown(body, digest))


def _order(trade: Trade) -> tuple[date, str]:
    return trade.signal_day, trade.symbol


VERDICTS = {
    "beats_random": "Out of sample, the walk-forward choice beat the 95th percentile of random entries.",
    "does_not_beat_random": "Out of sample, the walk-forward choice did not beat the 95th "
    "percentile of random entries.",
    "inconclusive": f"Inconclusive. Fewer than {MIN_OUT_OF_SAMPLE} out-of-sample trades resolved, "
    "or no candidate had enough training trades.",
}


def to_markdown(body: dict[str, Any], digest: str) -> str:
    params = {c["version"]: c["params"] for c in body["candidates"]}
    swept = sorted(
        k
        for k in params[body["candidates"][0]["version"]]
        if len({json.dumps(p[k]) for p in params.values()}) > 1
    )
    lines = [
        f"# Research: {body['strategy']}",
        "",
        f"Period {body['period'][0]} to {body['period'][1]}. {len(body['candidates'])} candidates, "
        f"{len(body['folds'])} walk-forward folds, at least {body['min_trades']} training trades to qualify.",
        f"Swept: {', '.join(swept) if swept else 'nothing'}.",
        f"Assets: {', '.join(body['assets'])}.",
        f"Report hash `{digest[:16]}`.",
        "",
        "## Verdict",
        "",
        VERDICTS[body["verdict"]],
        "",
    ]
    oos = body["out_of_sample"]["full_to_t2"]
    if oos.get("resolved"):
        ci = oos["expectancy_ci90_r"]
        lines.append(
            f"Out of sample (full_to_t2): {oos['resolved']} resolved, expectancy {oos['expectancy_r']}R "
            f"(90% interval {ci[0]}R to {ci[1]}R), win rate {oos['win_rate_pct']}%."
        )
    baseline = body["random_entry_baseline"]
    if baseline:
        lines.append(
            f"Random entries on the same windows, {baseline['runs']} runs: mean "
            f"{baseline['mean_expectancy_r']}R, 95th percentile {baseline['p95_r']}R."
        )
    lines += [
        "",
        "## Folds",
        "",
        "| Train to | Test window | Chosen | Test trades |",
        "| --- | --- | --- | --- |",
    ]
    for fold in body["folds"]:
        chosen = f"`{fold['chosen']}`" if fold["chosen"] else "none qualified"
        lines.append(
            f"| {fold['train'][1]} | {fold['test'][0]} to {fold['test'][1]} | {chosen} | "
            f"{len(fold['test_trades'])} |"
        )
    lines += [
        "",
        "## Candidates",
        "",
        "| Version | " + " | ".join(swept) + " |",
        "| --- |" + " --- |" * len(swept),
    ]
    for version, values in params.items():
        lines.append(f"| `{version}` | " + " | ".join(str(values[k]) for k in swept) + " |")
    if body["latest_choice"]:
        lines += [
            "",
            f"The latest fold chose `{body['latest_choice']}`. To use it, copy its parameters into "
            "settings.yaml, run `lens backtest` to store its report, and activate it yourself with "
            "`lens strategy activate` only if you accept the evidence.",
        ]
    lines += ["", "## Assumptions", "", *[f"- {a}" for a in body["assumptions"]]]
    lines += ["", "## Caveats", "", *[f"- {c}" for c in body["caveats"]], ""]
    return "\n".join(lines)
