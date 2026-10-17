# 0001. Run on scheduled jobs and managed services, with no server

Status: accepted, 2026-10-16.

## Context

v1 ran a long-lived bot process on a VPS. The owner does not want to maintain a server, and still wants a briefing on Telegram every day before 08:00 MYT.

The work splits into two shapes. The daily cycle is a batch job that runs for a few minutes once a day. Telegram commands are short requests that arrive at random times and must answer within seconds.

## Decision

- The daily cycle runs on GitHub Actions (`daily.yml`) with two cron triggers, 23:00 and 23:40 UTC.
- Telegram commands arrive by webhook at a Vercel Python function (`api/telegram.py`).
- State lives in managed PostgreSQL. Supabase is the default because its free tier includes a session pooler that GitHub's IPv4 runners can reach. Neon works with the same code.
- Healthchecks.io is the dead-man's switch. It alerts the owner through its own Telegram integration when no success ping arrives by 08:15 MYT.
- Backups are encrypted with `age` and kept as GitHub Actions artifacts for 35 days. A weekly job restores the newest one into a job-local database and compares row counts.

GitHub may start a scheduled job late or skip it. Three things cover that. Two triggers give a second chance. A per-day claim in `daily_cycles` makes the second trigger a no-op when the first succeeded. Healthchecks alerts when both fail.

## Consequences

- No process runs between briefings, so nothing needs patching or restarting.
- Commands that need the full pipeline (`/run`, `/watchlist add`) dispatch a GitHub workflow instead of running in the webhook. The webhook package stays small enough for Vercel's size limit.
- The runner has no disk that survives between runs. Degraded mode uses the Actions cache as its only cross-run memory ([ADR 0007](0007-degraded-mode.md)).
- The repository must stay private. GitHub disables scheduled workflows in public repositories after 60 days without activity.
- The free tiers set the limits. A private repository on GitHub Free has a monthly Actions-minutes allowance. The cycle itself took 8 seconds in a local dry run, so dependency installation sets most of each job's time; the `uv` cache keeps it short. Check each provider's current limits before adding work.
