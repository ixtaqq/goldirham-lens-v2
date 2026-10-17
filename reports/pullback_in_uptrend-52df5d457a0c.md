# Backtest: pullback_in_uptrend 52df5d457a0c

Period 2022-09-21 to 2026-10-16. Out of sample from 2025-02-28.
Assets: 1155.KL, 1295.KL, 5183.KL, AAPL, BNB-USD, BTC-USD, ETH-USD, MSFT, NVDA, QQQ, SOL-USD, SPY.
Report hash `e6f2b5105c67810b`.

## Results (exit model full_to_t2)

**All.** 106 resolved, expectancy 0.03R (90% interval -0.25R to 0.30R), win rate 28.3%, T1 touched 48.1%, max drawdown -23.67R.

**Out of sample.** 52 resolved, expectancy 0.06R (90% interval -0.31R to 0.49R), win rate 28.8%, T1 touched 40.4%, max drawdown -23.67R.

## Results (exit model half_at_t1_breakeven)

**All.** 106 resolved, expectancy 0.15R (90% interval -0.07R to 0.36R), win rate 48.1%, T1 touched 48.1%, max drawdown -17.75R.

## Baselines

Random entries with the same stops and targets, 100 runs: mean expectancy 0.27R (5th to 95th percentile -0.02R to 0.57R).

Buy and hold over the period:

- 1155.KL: 14.4%
- 1295.KL: 9.8%
- 5183.KL: -49.8%
- AAPL: 138.5%
- BNB-USD: 130.0%
- BTC-USD: 97.1%
- ETH-USD: -1.3%
- MSFT: 128.4%
- NVDA: 1681.4%
- QQQ: 170.5%
- SOL-USD: 13.5%
- SPY: 111.2%

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
