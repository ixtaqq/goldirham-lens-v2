# 0005. A strategy goes live only after a backtest, and only by the owner

Status: accepted, 2026-10-16.

## Context

v1 sent setups from rules nobody had tested on history. Its scorecard then measured those rules on live signals, which takes years to say anything.

## Decision

- Strategies run in research mode by default. Their decisions are stored and shown in `/why`, but they open no signals and the briefing shows no setups.
- `lens strategy activate <name> <version>` refuses a version without a stored backtest report. The owner runs it by hand.
- The backtest calls the same `decide()` and `advance()` code as the daily cycle.
- Entry is at the signal session's close, and evaluation starts with the next session. The live cycle does the same, so the scorecard and the backtest measure one thing. The build prompt's default was the next session's open. That would need the next session's bar before a setup could be stated, which the 07:00 briefing does not have.
- When one bar touches both the stop and a target, the stop wins. A gap below the stop fills at the open. No fees or slippage by default.
- The default exit model in reports is `full_to_t2`. `half_at_t1_breakeven` is reported beside it.
- Every report compares against random entries with the same stops and targets (100 runs) and buy and hold.

## First result

`reports/pullback_in_uptrend-52df5d457a0c.md`, over 2022-09-21 to 2026-10-16 on the 12-symbol watchlist:

| | Resolved | Expectancy | 90% interval | Win rate |
| --- | --- | --- | --- | --- |
| `full_to_t2`, all | 106 | 0.03R | -0.25R to 0.30R | 28.3% |
| `full_to_t2`, out of sample | 52 | 0.06R | -0.31R to 0.49R | 28.8% |
| `half_at_t1_breakeven`, all | 106 | 0.15R | -0.07R to 0.36R | 48.1% |
| Random entries, same stops and targets | | 0.27R mean | -0.02R to 0.57R (5th to 95th percentile) | |

The v1 rules did not beat random entries with the same risk geometry. The interval includes zero. The watchlist was chosen today, so survivorship flatters every row.

## Consequences

- The strategy was not activated. Whether to activate it is the owner's decision.
- The briefing's data status says no strategy is live, so an empty setups section reads as intended rather than broken.
- Any change to a strategy's parameters produces a new version, which needs its own report before activation.
