# 0003. Crypto uses the prior completed UTC day

Status: accepted as the default, 2026-10-16. The owner may choose the alternative below.

## Context

Exchanges publish daily crypto candles for the UTC day, which closes at 08:00 MYT. The briefing must arrive before 08:00 MYT. At the 07:00 MYT trigger, the current UTC day is still an hour from closing.

## Options

1. Use the latest completed UTC day and deliver by 08:00. The crypto rows are about 23 hours older than the stock rows.
2. Schedule the cycle after 00:05 UTC (08:05 MYT) to include the day that just closed, and accept a later briefing.
3. Use a partial candle. This breaks the rule that the system only reasons about completed sessions, so it was not considered further.

## Decision

Option 1. The `CRYPTO_UTC` calendar defines each session as 00:00 to 24:00 UTC, and `closed_sessions(now)` only returns sessions whose close is at or before `now`. The briefing prints each asset's session date, so the owner can see which day the crypto numbers describe.

## Consequences

- The briefing keeps its 08:00 deadline even when GitHub starts the job up to an hour late.
- Signals on crypto act a day later than they could. The backtest uses the same session rule, so its results include that delay.
- Switching to option 2 means changing the two cron lines in `daily.yml` and the Healthchecks schedule. No code changes.
