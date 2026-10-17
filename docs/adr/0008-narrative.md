# 0008. Optional AI narrative that cannot write numbers

Status: accepted, 2026-10-16. Disabled by default.

## Context

v1 asked a model to write the briefing, and the model sometimes wrote prices that did not match the data. A briefing for money decisions cannot contain a number Python did not compute.

## Decision

- The narrative is off (`narrative.enabled: false`). Turning it on is the owner's choice, and it costs money.
- The model receives a fact catalog built from the `BriefingDocument`. Each fact has an id, a label and a formatted value.
- The model returns JSON that matches a schema given through `output_config`. Its text may reference a number only as `{{f:ID}}`.
- `narrative/verifier.py` rejects the reply if the text contains any digit, percent sign, currency code, number word, or an id that is not in the catalog. Python then substitutes the values.
- A rejected or late reply drops the narrative section. The briefing still goes out on time.
- The `ai_usage` table records each call's estimated and actual cost. A reservation takes a Postgres advisory lock, so two runs cannot both pass the daily limit. The defaults are 3 calls and USD 0.50 a day.
- Token rates in settings carry a `rates_verified_on` date. `narrate()` refuses to run while it is null, so the owner must check current pricing first.
- Quantities, entry prices, account values and thesis notes stay out of the catalog unless the owner opts in.

The narrative runs inside the daily cycle when enabled, with a 45-second deadline. There is no separate schedule for it.

## Consequences

- Prose cannot contradict the numbers, because the prose contains none.
- Some natural sentences are impossible. "S&P 500" contains digits, so the catalog names the benchmark instead.
- The briefing is complete without the narrative, so the feature can stay off indefinitely.
