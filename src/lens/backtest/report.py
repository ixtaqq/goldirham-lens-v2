"""Backtest report: metrics for the whole period and the out-of-sample tail, with baselines."""

from __future__ import annotations

import hashlib
import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from lens.backtest.engine import (
    ASSUMPTIONS,
    AssetHistory,
    Trade,
    buy_and_hold_pct,
    run_random_baseline,
    run_strategy,
)
from lens.domain.evaluation import SignalStatus
from lens.domain.scorecard import bootstrap_interval
from lens.domain.strategy.base import RiskInputs
from lens.domain.strategy.registry import ConfiguredStrategy

OUT_OF_SAMPLE_SHARE = Decimal("0.4")
CAVEATS = (
    "Survivorship: the watchlist was chosen today, so history favours assets that did well.",
    "Small samples: a handful of trades says little; read the interval, not the point estimate.",
    "Bars that failed quality checks were excluded, so some sessions are missing.",
    "Past behaviour of these rules is not a promise about future results.",
)


def _resolved(trades: Sequence[Trade]) -> list[Trade]:
    return [
        t
        for t in trades
        if t.status in (SignalStatus.STOPPED, SignalStatus.T2_HIT, SignalStatus.EXPIRED)
        and t.outcome_r is not None
    ]


def _drawdown(outcomes: Sequence[Decimal]) -> Decimal:
    peak = equity = worst = Decimal(0)
    for value in outcomes:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def summarize(trades: Sequence[Trade], scaled: bool = False) -> dict[str, Any]:
    resolved = _resolved(trades)
    outcomes = [
        (t.outcome_r_scaled if scaled and t.outcome_r_scaled is not None else t.outcome_r)
        for t in sorted(resolved, key=lambda t: (t.exit_day or t.signal_day, t.symbol))
    ]
    values = [o for o in outcomes if o is not None]
    if not values:
        return {"resolved": 0, "open": sum(t.status is SignalStatus.OPEN for t in trades)}
    n = len(values)
    low, high = bootstrap_interval(values) if n >= 2 else (values[0], values[0])
    quartiles = statistics.quantiles(values, n=4, method="inclusive") if n >= 4 else None
    return {
        "resolved": n,
        "open": sum(t.status is SignalStatus.OPEN for t in trades),
        "t1_touch_rate_pct": str(
            (Decimal(sum(t.t1_touched for t in resolved)) / n * 100).quantize(Decimal("0.1"))
        ),
        "win_rate_pct": str(
            (Decimal(sum(v > 0 for v in values)) / n * 100).quantize(Decimal("0.1"))
        ),
        "expectancy_r": str((sum(values, Decimal(0)) / n).quantize(Decimal("0.01"))),
        "expectancy_ci90_r": [str(low), str(high)],
        "max_drawdown_r": str(_drawdown(values).quantize(Decimal("0.01"))),
        "r_quartiles": [str(q.quantize(Decimal("0.01"))) for q in quartiles] if quartiles else None,
        "median_sessions_held": int(statistics.median(t.sessions_held for t in resolved)),
    }


@dataclass(frozen=True, slots=True)
class Report:
    body: dict[str, Any]
    report_hash: str
    markdown: str


def build_report(
    histories: Sequence[AssetHistory],
    configured: ConfiguredStrategy,
    risk: RiskInputs,
    *,
    start: date,
    end: date,
    min_sessions: int = 200,
    baseline_runs: int = 200,
) -> Report:
    trades = run_strategy(
        histories, configured, risk, start=start, end=end, min_sessions=min_sessions
    )
    cutoff = start + timedelta(days=int((end - start).days * (1 - OUT_OF_SAMPLE_SHARE)))
    oos = [t for t in trades if t.signal_day >= cutoff]
    per_asset: dict[str, int] = {}
    for trade in trades:
        per_asset[trade.symbol] = per_asset.get(trade.symbol, 0) + 1
    random_means = run_random_baseline(
        histories,
        configured,
        risk,
        start=start,
        end=end,
        trades_per_asset=per_asset,
        runs=baseline_runs,
        min_sessions=min_sessions,
    )
    random_sorted = sorted(random_means)
    baseline = None
    if random_sorted:
        baseline = {
            "runs": len(random_sorted),
            "mean_expectancy_r": str(
                (sum(random_sorted, Decimal(0)) / len(random_sorted)).quantize(Decimal("0.01"))
            ),
            "p05_r": str(random_sorted[int(0.05 * len(random_sorted))].quantize(Decimal("0.01"))),
            "p95_r": str(
                random_sorted[max(0, int(0.95 * len(random_sorted)) - 1)].quantize(Decimal("0.01"))
            ),
        }
    body: dict[str, Any] = {
        "strategy": configured.name,
        "version": configured.version,
        "params": configured.params.model_dump(mode="json"),
        "period": [start.isoformat(), end.isoformat()],
        "out_of_sample_from": cutoff.isoformat(),
        "assets": sorted(h.instrument.symbol for h in histories),
        "assumptions": list(ASSUMPTIONS),
        "caveats": list(CAVEATS),
        "full_to_t2": {"all": summarize(trades), "out_of_sample": summarize(oos)},
        "half_at_t1_breakeven": {
            "all": summarize(trades, scaled=True),
            "out_of_sample": summarize(oos, scaled=True),
        },
        "random_entry_baseline": baseline,
        "buy_and_hold_pct": {
            h.instrument.symbol: (
                str(v) if (v := buy_and_hold_pct(h, start, end)) is not None else None
            )
            for h in sorted(histories, key=lambda h: h.instrument.symbol)
        },
        "per_asset_trades": dict(sorted(per_asset.items())),
        "trades": [
            {
                "symbol": t.symbol,
                "signal_day": t.signal_day.isoformat(),
                "exit_day": t.exit_day.isoformat() if t.exit_day else None,
                "status": t.status.value,
                "entry": str(t.entry),
                "outcome_r": None
                if t.outcome_r is None
                else str(t.outcome_r.quantize(Decimal("0.01"))),
            }
            for t in sorted(trades, key=lambda t: (t.signal_day, t.symbol))
        ],
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return Report(body, digest, to_markdown(body, digest))


def to_markdown(body: dict[str, Any], digest: str) -> str:
    def block(title: str, summary: dict[str, Any]) -> list[str]:
        if not summary.get("resolved"):
            return [f"**{title}.** No resolved trades."]
        ci = summary["expectancy_ci90_r"]
        return [
            f"**{title}.** {summary['resolved']} resolved, expectancy {summary['expectancy_r']}R "
            f"(90% interval {ci[0]}R to {ci[1]}R), win rate {summary['win_rate_pct']}%, "
            f"T1 touched {summary['t1_touch_rate_pct']}%, max drawdown {summary['max_drawdown_r']}R.",
        ]

    lines = [
        f"# Backtest: {body['strategy']} {body['version']}",
        "",
        f"Period {body['period'][0]} to {body['period'][1]}. Out of sample from {body['out_of_sample_from']}.",
        f"Assets: {', '.join(body['assets'])}.",
        f"Report hash `{digest[:16]}`.",
        "",
        "## Results (exit model full_to_t2)",
        "",
        *block("All", body["full_to_t2"]["all"]),
        "",
        *block("Out of sample", body["full_to_t2"]["out_of_sample"]),
        "",
        "## Results (exit model half_at_t1_breakeven)",
        "",
        *block("All", body["half_at_t1_breakeven"]["all"]),
        "",
        "## Baselines",
        "",
    ]
    baseline = body["random_entry_baseline"]
    if baseline:
        lines.append(
            f"Random entries with the same stops and targets, {baseline['runs']} runs: mean expectancy "
            f"{baseline['mean_expectancy_r']}R (5th to 95th percentile {baseline['p05_r']}R to {baseline['p95_r']}R)."
        )
    lines += ["", "Buy and hold over the period:", ""]
    lines += [
        f"- {symbol}: {value}%" if value is not None else f"- {symbol}: not enough data"
        for symbol, value in body["buy_and_hold_pct"].items()
    ]
    lines += [
        "",
        "## Assumptions",
        "",
        *[f"- {a}" for a in body["assumptions"]],
        "",
        "## Caveats",
        "",
        *[f"- {c}" for c in body["caveats"]],
        "",
    ]
    return "\n".join(lines)
