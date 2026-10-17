# 0004. Market data providers and cross-checks

Status: accepted, 2026-10-16.

## Context

v1 pulled every asset from Yahoo Finance and trusted it. A bad bar from one source could become a setup. The build prompt asks for a primary source and an independent cross-check per market, using free sources only.

## Decision

| Market | Primary | Cross-check | Notes |
| --- | --- | --- | --- |
| US stocks and ETFs | Yahoo Finance via `yfinance` | Alpha Vantage `TIME_SERIES_DAILY` | `yfinance` is unofficial. Alpha Vantage needs a free key and has a small daily request limit; check the current limit before adding US symbols. |
| Bursa Malaysia | Yahoo Finance via `yfinance` | None | No free second source was found. Bursa bars stay `single_source`, which readiness allows for Bursa. |
| BTC, ETH, SOL | Coinbase Exchange public candles | Yahoo Finance | No key. Coinbase's UTC daily candles match the `CRYPTO_UTC` session. |
| BNB | Binance public market data (`data-api.binance.vision`, BNBUSDT) | Yahoo Finance | Coinbase does not list BNB. The USDT pair is treated as USD. |
| FX into MYR | Bank Negara Malaysia public API | ECB rates through Frankfurter | |
| Context | alternative.me Fear and Greed index, RSS headlines | None | Context is shown, never used in a rule. |

The cross-check compares closes over the latest 5 sessions with a 2% tolerance. A difference above that marks the bar `disputed`, which blocks setups on that asset.

### Stooq was dropped

The build prompt listed Stooq as a candidate US cross-check. When tested on 2026-10-16, Stooq's CSV endpoint returned a JavaScript bot challenge instead of data. Getting past that would mean defeating a bot check, which this project does not do. Alpha Vantage replaced it.

## Consequences

- Until `ALPHA_VANTAGE_API_KEY` is set, US bars are `single_source` in the cross-check window, so US assets get no setups. `lens readiness` and the briefing's data status say so.
- `provider-drift.yml` runs weekly against each provider and opens a GitHub issue when a response shape changes.
- Before relying on any provider, check its current terms of use. `yfinance` in particular depends on endpoints Yahoo does not document.
