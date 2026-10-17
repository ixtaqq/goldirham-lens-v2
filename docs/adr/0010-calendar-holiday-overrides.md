# 0010. Owner-maintained holiday overrides for exchange calendars

Status: accepted, 2026-10-16.

## Context

Readiness requires every session of the last 200 to be present. On the first live run, all three Bursa stocks lacked bars for 2026-03-20 and 2026-06-02, and none was ready. Bursa was closed on both days, but `exchange_calendars` lists them as sessions. A calendar that disagrees with the exchange blocks every asset on that exchange.

## Decision

- `calendar_holidays` in `config/settings.yaml` lists extra closed days per market. `calendar_for(market, extra_holidays)` removes them from the session list.
- `calendar_gaps` in `data/collect.py` finds sessions that every asset of one market lacks. `lens readiness` prints them as likely calendar errors rather than as missing data.
- The runbook says to confirm the day on the exchange's own holiday list before adding it.

## Consequences

- One config line fixes a whole market, and the fix is visible in review.
- A wrong entry would hide a real session. Confirming against the exchange's list is the guard.
- When `exchange_calendars` adds the holiday upstream, the override becomes redundant and harmless.
