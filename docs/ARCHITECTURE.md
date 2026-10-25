# Architecture

Goldirham Lens turns public market data into one Telegram briefing a day for one owner. This page explains how the parts fit and why they are split the way they are. For setup steps, see [RUNBOOK.md](RUNBOOK.md). For the rules and metrics, see [STRATEGY.md](STRATEGY.md).

## Where each part runs

Nothing runs on a server the owner maintains.

| Part | Runs on | Started by |
| --- | --- | --- |
| Daily cycle | GitHub Actions `daily.yml` | Cron at 23:00 and 23:40 UTC (07:00 and 07:40 MYT), or a dispatch |
| Telegram commands | Vercel Python function `api/telegram.py` | A Telegram webhook request |
| Data | Managed PostgreSQL (Supabase by default) | Both of the above |
| Missed-run alert | Healthchecks.io | No success ping by 08:15 MYT |
| Backups and restore drills | GitHub Actions `backup.yml`, `restore-drill.yml` | Cron |
| Showcase | Vercel project for `web/` | Push to `main` |
| Private dashboard (optional) | A second Vercel project for `api/dashboard.py` | The owner's browser, after Telegram sign-in |

GitHub can start a scheduled run late or skip it. Two triggers, one database lock per day, and the Healthchecks dead-man's switch together make a missed or doubled briefing unlikely and loud. [ADR 0001](adr/0001-serverless-architecture.md) records the choice.

## The daily cycle

`lens cycle run` in `src/lens/pipeline/cycle.py` does the work in this order:

1. Ping Healthchecks `/start`, connect to the database, and check that its Alembic revision equals the code's head.
2. Claim the day in `daily_cycles`. A second trigger finds `DONE` or a fresh `RUNNING` claim and exits. A claim older than 20 minutes is adopted, so a crashed run does not block the day.
3. **Gather** (`gather.py`) reads the watchlist, ledger, open signals, the previous briefing and the active strategy versions, then collects bars, FX and context from providers. It returns one `CycleInputs` snapshot.
4. **Analyze** (`analysis.py`) is a pure function of `CycleInputs`. It produces decisions, signal progress, marks, the portfolio snapshot, holding reviews and the market regime.
5. **Persist** stores bars, decisions, new signals, signal events and reviews.
6. **Narrate** runs only when `narrative.enabled` is true. Its output becomes part of `CycleInputs`.
7. **Compose** (`compose.py`) is pure. It builds a `BriefingDocument`, and `delivery/renderer.py` turns that into Telegram HTML chunks.
8. **Store** saves the document, the chunks and the packed inputs in `briefings`, plus a `COMPOSED` row in `deliveries`.
9. **Deliver** (`delivery/sender.py`) sends each chunk that has no message id yet, then settles the delivery.
10. Release the day, finish the run record, and ping Healthchecks.

Every stage writes a `stage_runs` row with its timing and outcome, so `/health` can show where time went.

### Why gather, analyze and compose are separate

Analysis and composition read only `CycleInputs`, never the network or the database. That one rule buys three things. `lens replay` rebuilds any stored briefing from its packed inputs and compares it byte for byte. The backtest can call the same decision code without a database. Tests build inputs by hand and check the rendered text against golden files.

## Delivery states

A delivery moves through these states:

```
COMPOSED -> SENDING -> SENT
                    -> HELD    a timeout or network error after a chunk may have arrived
                    -> HELD    the sender died mid-send and nothing touched it for 10 minutes
                    -> HELD    the send deadline passed before every chunk was sent
                    -> FAILED  Telegram certainly accepted nothing; the next trigger retries
HELD -> RESENT (the owner taps Resend in /held) or DISMISSED
```

Each chunk's Telegram message id is written as soon as Telegram accepts it. A resend sends only the chunks without an id. A delivered briefing is never replaced, even if a later run composes a new one.

A run killed mid-send, by the job timeout or by Vercel's 30-second limit during a resend, leaves its delivery in `SENDING`. The next trigger, or the owner's next `/held`, moves a `SENDING` delivery older than 10 minutes to `HELD` and clears its claim, so the dead sender can record nothing more. A resend from `/held` starts no new chunk after 6 seconds, which keeps it inside the Vercel limit; `tests/test_time_budgets.py` checks those numbers against `vercel.json`.

## When the database is unreachable

The runner has no disk that survives between runs. If the database does not answer, or its schema is behind the code, the cycle builds a degraded briefing from live provider data alone. Portfolio, signals and setups need the database, so the briefing says they are skipped. A marker in the GitHub Actions cache, keyed by the briefing date, stops a second degraded send that day. The run still pings Healthchecks `/fail`, so the owner hears about the outage.

## Package layout

```text
src/lens/
  domain/      pure rules: instruments, sessions, money and ticks, bars, indicators, validation,
               readiness, strategies, risk, holding reviews, evaluation, scorecard, portfolio, facts,
               the BriefingDocument
  data/        provider adapters, calendars, the collector
  storage/     SQLAlchemy models and one repository per aggregate
  pipeline/    gather, analysis, compose, persist, cycle, replay
  delivery/    renderer, chunker, Telegram client, delivery state machine
  bot/         update parsing, owner guard, router, commands
  narrative/   optional AI: schema, prompt, placeholder verifier, budgeted service
  backtest/    replay engine and report
  ops/         doctor, health pings, backup manifest and restore guard, alert jobs
  dashboard/   owner-only FastAPI pages: Telegram sign-in, read-only queries, server-rendered HTML
  webhook.py   FastAPI app for Telegram updates
  cli.py       the `lens` command
```

`import-linter` enforces five contracts in `pyproject.toml`. The domain imports nothing else from `lens` and no I/O library. The backtest imports only the domain. The bot, delivery and webhook never import the data layer, the pipeline, numpy or pandas, which keeps the Vercel function small. The dashboard reads stored data only: no data layer, pipeline, narrative, bot or outbound HTTP ([ADR 0011](adr/0011-private-dashboard.md)).

## Typed contracts between stages

| Contract | Defined in | Produced by | Read by |
| --- | --- | --- | --- |
| `Bar`, `BarQuality` | `domain/bars.py` | provider adapters, quality rules | everything downstream |
| `Readiness` | `domain/readiness.py` | the collector | analysis, `/readiness` |
| `MarketView` | `domain/market_view.py` | analysis, backtest | strategies, indicators, reviews |
| `Decision`, `Setup` | `domain/strategy/base.py` | strategies | persistence, compose, `/why` |
| `SignalState`, `Event` | `domain/evaluation.py` | `advance()` | persistence, compose, scorecard |
| `PortfolioSnapshot` | `domain/portfolio.py` | `value_portfolio()` | compose, `/portfolio` |
| `CycleInputs` | `pipeline/inputs.py` | gather | analysis, compose, replay |
| `BriefingDocument` | `domain/briefing.py` | compose | renderers, replay, the fact catalog |

## Numbers come only from Python

Prices and money are `Decimal` from the provider boundary onward. Setup levels are quantised to the instrument's price increment before any rule checks them. The optional narrative may reference a number only as a `{{f:ID}}` placeholder. `narrative/verifier.py` rejects any digit, percent sign, currency code or number word the model writes itself, then Python substitutes the values. [ADR 0008](adr/0008-narrative.md) has the details.
