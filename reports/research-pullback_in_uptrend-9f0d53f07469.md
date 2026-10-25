# Research: pullback_in_uptrend

Period 2022-09-28 to 2026-10-24. 12 candidates, 3 walk-forward folds, at least 10 training trades to qualify.
Swept: atr_stop_multiple, rsi_trigger.
Assets: 1155.KL, 1295.KL, 5183.KL, AAPL, BNB-USD, BTC-USD, ETH-USD, MSFT, NVDA, QQQ, SOL-USD, SPY.
Report hash `9f0d53f0746961b7`.

## Verdict

Out of sample, the walk-forward choice did not beat the 95th percentile of random entries.

Out of sample (full_to_t2): 74 resolved, expectancy -0.11R (90% interval -0.41R to 0.19R), win rate 25.7%.
Random entries on the same windows, 100 runs: mean 0.07R, 95th percentile 0.35R.

## Folds

| Train to | Test window | Chosen | Test trades |
| --- | --- | --- | --- |
| 2024-10-09 | 2024-10-10 to 2025-06-14 | `312ef8879384` | 33 |
| 2025-06-14 | 2025-06-15 to 2026-02-17 | `ee000d2e772d` | 24 |
| 2026-02-17 | 2026-02-18 to 2026-10-24 | `d2611ed55597` | 26 |

## Candidates

| Version | atr_stop_multiple | rsi_trigger |
| --- | --- | --- |
| `7975aa1af5a3` | 1.5 | 20 |
| `090f3d4d556d` | 2.0 | 20 |
| `d2611ed55597` | 2.5 | 20 |
| `e610b86f225f` | 1.5 | 25 |
| `52df5d457a0c` | 2.0 | 25 |
| `ee000d2e772d` | 2.5 | 25 |
| `f9b296cc8de6` | 1.5 | 30 |
| `ce6f5a8af9de` | 2.0 | 30 |
| `d44212838195` | 2.5 | 30 |
| `312ef8879384` | 1.5 | 35 |
| `ee3679f9961a` | 2.0 | 35 |
| `246bb77f533d` | 2.5 | 35 |

The latest fold chose `d2611ed55597`. To use it, copy its parameters into settings.yaml, run `lens backtest` to store its report, and activate it yourself with `lens strategy activate` only if you accept the evidence.

## Assumptions

- Entry at the signal session's close; evaluation starts the next session.
- When one bar touches both the stop and a target, the stop wins.
- A gap below the stop fills at that session's open.
- One open trade per asset at a time; no fees or slippage.
- Fundamentals are not point-in-time, so the fundamentals rule is skipped.

## Caveats

- Survivorship: the watchlist was chosen today, so history favours assets that did well.
- Small samples: a handful of trades says little; read the interval, not the point estimate.
- Bars that failed quality checks were excluded, so some sessions are missing.
- Past behaviour of these rules is not a promise about future results.
- Every candidate tried raises the chance one looks good by luck; only the walk-forward result counts, and a wider sweep needs a stronger result.
