# 0007. Degraded briefing when the database is unavailable

Status: accepted, 2026-10-16.

## Context

Free managed databases can pause, go down or fall behind a migration. v1 sent nothing when its database failed, so an outage looked the same as a quiet market. The runner has no disk that survives between runs, so the usual once-a-day lock is unavailable exactly when the database is.

## Decision

When the database does not answer, or its Alembic revision differs from the code's head, `run_degraded` builds a briefing from live provider data alone. It shows benchmarks, the watchlist's closes and data quality, and a banner that names the cause. Portfolio, signals and setups need stored state, so the briefing lists them as skipped.

`daily.yml` keeps a marker in the GitHub Actions cache keyed by the briefing date. The step restores it before the cycle and saves it when the cycle exits with code 3 (degraded briefing sent). A second trigger that finds the marker sends nothing.

The run pings Healthchecks `/fail`, so the owner also gets an outage alert.

Daily briefings are not uploaded as workflow artifacts, in degraded mode or otherwise. They contain portfolio values, and artifacts are visible to anyone with read access to the repository.

## Consequences

- The owner always gets a message by 08:00 when the providers work, and can tell an outage from a quiet day.
- A cache eviction between the two triggers could allow a second degraded briefing that day. Both say the same thing, so the cost is one extra message.
- A degraded briefing is not stored, so it cannot be replayed.
