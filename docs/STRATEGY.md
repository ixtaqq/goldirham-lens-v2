# Strategy reference

The rules, reason codes and metric definitions the code uses. Values come from `config/settings.yaml`. Each strategy's parameters hash into a 12-character `strategy_version`; any change produces a new version.

## Readiness

An asset is ready when the last `data.min_sessions` (200) closed sessions on its exchange calendar are all present and usable, and the newest bar is the latest closed session.

| Market | Calendar | Session |
| --- | --- | --- |
| US (`XNYS`) | `exchange_calendars` XNYS | Exchange hours, closes 16:00 New York time |
| Bursa (`XKLS`) | `exchange_calendars` XKLS minus `calendar_holidays.XKLS` | Exchange hours |
| Crypto (`CRYPTO_UTC`) | Every UTC day | 00:00 to 24:00 UTC |

A bar is usable when its quality is `verified`, or `single_source` where allowed. `single_source` is allowed for Bursa, and for any market outside the latest `data.cross_check_sessions` (5) sessions.

## Bar quality rules

The collector applies these to each bar, oldest first.

| Quality | Rule |
| --- | --- |
| `invalid` | A value is not finite, `low <= 0`, `volume < 0`, or `low <= min(open, close) <= max(open, close) <= high` fails. |
| `corporate_action_pending` | The close moved by a split ratio (2, 3, 4, 5, 10, 1.5, or the inverse) within 1%, and the provider reported no split that day. Never applied to crypto. |
| `suspect` | The close moved more than `suspect_jump_pct` (20% stocks and ETFs, 35% crypto) and volume was under half its 20-session average. |
| `disputed` | Within the cross-check window, the primary and cross-check closes differ by more than 2%. |
| `single_source` | Within the cross-check window, no cross-check close was available. |
| `verified` | None of the above. |

## pullback_in_uptrend

The v1 rule set, kept as the baseline. Every rule is evaluated, so `/why` shows the full trail.

| Rule | Passes when | Reason codes |
| --- | --- | --- |
| Trend | 50-session average > 1.05 x 200-session average | `trend_ok`, `trend_filter_failed` |
| Floor | close >= 0.85 x 200-session average | `floor_ok`, `below_floor` |
| Volatility | ATR14 / close <= 8% | `volatility_ok`, `volatility_too_high` |
| Trigger | RSI14 < 25, or close within 1% of the latest confirmed swing low (radius 2) | `rsi_trigger`, `support_trigger`, `no_pullback_trigger` |
| Fundamentals (stocks only) | P/E in (0, 100] and revenue growth >= -20%, when known | `fundamentals_ok`, `fundamentals_excluded`, `fundamentals_unavailable` |

## breakout_52w

Disabled. Research only until a backtest report exists for its version.

| Rule | Passes when |
| --- | --- |
| Breakout | close > highest high of the prior 252 sessions |
| Volume | session volume >= 1.5 x the prior 50-session average |

## Setup arithmetic

Both strategies build a long setup the same way, in `domain/risk.py`.

1. Entry is the close, rounded to the nearest price increment.
2. The stop is entry minus 2 x ATR14, rounded down to the increment.
3. If rounding widened the stop by more than 1.5 x the ATR rule, or the stop is not above zero, there is no setup (`precision_too_coarse`, `stop_not_positive`).
4. T1 is entry + 1.5R and T2 is entry + 3R, both rounded down.
5. The setup requires `stop < entry < T1 < T2` and reward to risk >= 2.0 after rounding.
6. Size is risk per trade (1%) divided by the stop distance, capped at 20% of equity, rounded down to 0.01%.

If the owner's exposure to the asset class is at or above its cap (`risk.max_asset_class_pct`, crypto 30%), the setup is withheld with `asset_class_cap_reached`.

Price increments live under `ticks` in settings. [ADR 0006](adr/0006-tick-sizes.md) records their source.

## Holding reviews

Reviewed daily from completed sessions. The most severe finding sets the action.

| Action | Rule | Reason code |
| --- | --- | --- |
| EXIT | Close below the highest close since entry minus 3 x ATR14 | `below_chandelier_stop` |
| EXIT | Close below the 200-session average for 3 sessions in a row | `below_ma200` |
| REDUCE | Position weight above 20% of the portfolio | `above_concentration_cap` |
| REVIEW | Drawdown from the post-entry peak >= 25% | `drawdown_from_peak` |
| REVIEW | No verified price, or the latest verified price is not current | `mark_unavailable`, `mark_stale` |
| HOLD | No rule fired | `holding_ok` |

## Signal evaluation

A signal opens on a live strategy's setup. Entry is the signal session's close. Evaluation starts with the next closed session and runs one session at a time.

- A bar that touches the stop ends the signal as `STOPPED`, even if the same bar also reached a target. A gap below the stop fills at the open.
- A bar that reaches T2 ends the signal as `T2_HIT`.
- The first bar that reaches T1 records `T1_TOUCHED`. The signal stays open.
- The first session after `expiry_days` (120) ends the signal as `EXPIRED` at the last close inside the window.
- A missing or unusable bar pauses evaluation at that session.
- A signal still unevaluated 7 days after expiry becomes `UNVERIFIABLE`. It is counted, never rated.

Two exit models run side by side. `full_to_t2` holds the whole position to the stop, T2 or expiry. `half_at_t1_breakeven` sells half at T1 and moves the stop on the rest to entry.

## Scorecard metrics

The scorecard covers signals from the last 365 days. With fewer than 20 resolved signals it shows counts only.

| Metric | Definition |
| --- | --- |
| Resolved | Signals that stopped, hit T2, or expired with a verified price |
| T1-touch rate | Share of resolved signals whose price reached T1 at any point |
| Win rate | Share of resolved signals whose final outcome was above 0R under the named exit model |
| Expectancy | Mean outcome in R per resolved signal under the named exit model |
| Interval | 90% bootstrap interval for expectancy, 2,000 resamples, fixed seed |
| Median hold | Median calendar days from signal to exit |

## Backtest

`lens backtest` replays history through the same `decide()` and `advance()` code. Its report states the execution assumptions, splits results into the whole period and the out-of-sample tail (the last 40% of the period), and compares against two baselines: random entries with the same stops and targets, and buy and hold. `lens strategy activate` refuses a version without a stored report. The first report for `pullback_in_uptrend` is in [ADR 0005](adr/0005-backtest-and-activation.md).

## Research

`lens research` sweeps a grid of parameter values with walk-forward testing. The last half of the period is split into equal test windows. Each fold trains on everything from the start of the period to the day before its test window, and sees no bar after that day, so a trade still open at the end of training cannot take its result from the future. Among candidates with at least `--min-trades` resolved training trades, the highest training expectancy wins, and it then trades the test window. The out-of-sample result is every test window together. It is compared with random entries using the chosen stops and targets on the same windows, with as many trades per asset.

The verdict is "beats random" only when there are at least 20 resolved out-of-sample trades and their expectancy is above the 95th percentile of the random runs. With fewer trades the verdict is inconclusive. Every extra candidate raises the chance that one looks good by luck, so only the walk-forward result counts. Research never changes settings or activates anything.

## Price level alerts

An alert names a symbol, a direction (above or below) and a level. It fires on the first completed session after the day it was set whose close is verified and at or beyond the level. A close exactly at the level counts. Suspect, disputed or single-source closes are skipped, as everywhere else. A fired alert appears once in the next briefing with its session date and close, and is then done.

## Weekly digest

On the configured weekday, the briefing compares each asset's latest usable close with its last usable close at least seven days earlier. It shows benchmarks, holdings, and the largest gains and losses on the watchlist (three each by default). A line whose dates differ from the section's range shows its own dates.
