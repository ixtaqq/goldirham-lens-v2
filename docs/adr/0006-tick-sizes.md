# 0006. Price increments per market

Status: accepted, 2026-10-16. Check the values against each exchange's current rules before activating a strategy.

## Context

v1 printed stops and targets with arbitrary decimals, such as a Bursa stop at 4.3127. An order at that price cannot be placed. Rounding after the risk check can also make the reward to risk worse than the number shown.

## Decision

Setup levels are rounded to the market's price increment before any rule checks them. Entry rounds to the nearest increment. The stop and both targets round down, so rounding never makes a setup look better than it is. If rounding widens the stop by more than 1.5 times the ATR rule, there is no setup.

The bands live under `ticks` in `config/settings.yaml`:

| Market | Price below | Increment |
| --- | --- | --- |
| US | 1.00 | 0.0001 |
| US | otherwise | 0.01 |
| Bursa | 1.00 | 0.005 |
| Bursa | 10.00 | 0.01 |
| Bursa | 100.00 | 0.02 |
| Bursa | otherwise | 0.10 |
| Crypto | 1.00 | 0.00001 |
| Crypto | 100.00 | 0.001 |
| Crypto | otherwise | 0.01 |

The US bands follow the SEC's sub-penny rule (Rule 612). The Bursa bands follow Bursa Malaysia's published price spreads for its main market. The crypto bands are a display choice, because each exchange sets its own increment per pair. Check them against the exchange's product details before activating a strategy on crypto.

## Consequences

- A low-priced stock can lose its setup to `precision_too_coarse`, which is correct. A 2-ATR stop narrower than two increments cannot be placed.
- The bands are not part of the strategy version hash. A band change alters setup levels without a new version, so rerun the backtest after one and note it in `CHANGELOG.md`.
