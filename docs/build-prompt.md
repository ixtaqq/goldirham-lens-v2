# Build Goldirham Lens v2 from scratch

You are the lead engineer building **Goldirham Lens v2** in an empty repository. You own architecture, code, tests, docs and operations tooling. Work in phases (Section 24) using the required skills and workflow (Section 25). Every phase ends on checkable exit criteria, and you report the evidence for each one before starting the next.

If you have read access to the v1 repository (`goldirham-lens`, tag `v1.0.0-rc.1`), treat it as a reference for *behaviour and lessons*, not for structure. Do not copy its layout.

---

## 1. Mission

Goldirham Lens is a private, numbers-first investment research service for **one owner**: a long-horizon investor in Malaysia who holds crypto, US stocks/ETFs and Bursa Malaysia stocks.

Every morning it collects public market data, verifies it, computes indicators, candidate setups, holding reviews and portfolio state in Python, and delivers **one concise briefing** to the owner's private Telegram chat before **08:00 Asia/Kuala_Lumpur**, every single day. Most days the right answer is "nothing new". The product is meant to be boring and trustworthy.

**There is no server to maintain.** A scheduled GitHub Actions workflow runs the daily cycle and sends the briefing. A small serverless Telegram webhook on Vercel answers commands. Data lives in a free managed PostgreSQL. The owner never deploys or patches a VPS.

It is research and decision support. It never places trades, never connects to a broker, and never gives personalised financial advice. Every briefing says so in its footer.

---

## 2. Principles

These terms are the project's vocabulary. Use them in code, docs, reason codes and commit messages.

- **Python owns the facts.** Every number the owner sees (price, level, size, P&L, metric) is computed by deterministic code and rendered by Python with its unit, session date and source. A language model may write words. It never writes a number.
- **Completed sessions.** Analysis uses only daily bars whose exchange session has closed, checked against that exchange's calendar. Live quotes are labelled context and never feed analysis.
- **Provenance.** Every fact carries its source, session date, freshness (`fresh` / `stale` / `unavailable`) and quality status. Missing data is shown as unavailable. Nothing is ever filled in from a different value, such as the entry price.
- **Fail closed.** Suspect, disputed, stale or insufficient data produces no setup and a stated reason. An uncertain delivery is held for review, not resent.
- **Silence is valid.** Zero setups is a normal, good day. Never pad a briefing.
- **Replayable.** Every briefing can be rebuilt byte-for-byte from its stored inputs, strategy version and code version.
- **Evidence before activation.** A strategy version goes live only after a walk-forward backtest report exists for that exact version.
- **Owner-scoped.** One owner is enforced at runtime, and every owner-specific row carries `owner_id` from the first migration. Growth never needs a data migration, but multi-user remains a non-goal.

---

## 3. Lessons from v1

### Keep: v1 got these right

- Deterministic setups: ATR-based stop, R-multiple targets, fractional position sizing with a concentration cap.
- Exchange calendars (`exchange_calendars`) and a 200-contiguous-verified-session readiness rule per asset.
- Live quotes kept separate from completed daily bars; suspect bars quarantined. A cross-provider disagreement above 2% is quarantined.
- Delivery claims that prevent duplicate briefings. An ambiguous Telegram send is held, not resent.
- A fallback briefing when the database is down. v2 builds it statelessly from live data (Section 14).
- Every Telegram command checks owner ID and private chat, plus a test that every handler is wrapped.
- AI budget reservations written before the request, with unknown outcomes kept on the books.
- Chronological signal evaluation with a cursor that resolves stop-first, and an outcome tracker that excludes unverifiable signals.
- Operational discipline: encrypted backups, restore verification against an isolated database, secret scanning, Healthchecks pings. v1 ran these with systemd on a VPS; v2 runs them as GitHub Actions workflows.
- v1's pausable ambient canvas and its cursor "lens" were the right ideas. v2 rebuilds them as the full motion system in Section 20.1.
- Brand: "Numbers before narrative." Palette Carbon `#07110E`, Graphite `#101A16`, Paper `#F0EEE7`, Fog `#8D9992`, Oxidized mint `#79D5C2` (the single accent, used only as evidence), Loss `#E88078`. Type: Barlow Condensed (display), Geist Sans (UI), Geist Mono (data and provenance). Ruled ledgers, square corners, no glass cards, no trading-floor imagery.

### Fix: v1 limits and the v2 requirement for each

| # | v1 limit | v2 requirement |
|---|---|---|
| 1 | One hard-coded rule set with thresholds as module constants. The only evidence is a forward scorecard, and there is no backtest. | Strategy parameters live in versioned config, hashed into a `strategy_version`. A backtest/walk-forward engine runs the **same code path** as live and compares results with baselines (Section 10). |
| 2 | The AI layer only picks fact IDs, never runs on schedule, reserves the full 200k-token context cost (USD 0.206) on every call, uses forced `tool_choice`, and is pinned to an older model. | Placeholder narrative: the model writes short sentences containing `{{f:ID}}` placeholders, a verifier rejects any digit, and Python fills in the values. Reservations use exact token counts. Output comes from structured outputs. It can run on schedule within budget, and the deterministic briefing is always the fallback (Section 16). |
| 3 | `main.py` and `operations.py` are each about 1,000 lines. Contracts are fallback-shaped dicts with `getattr` duck typing. A new DB engine is created per command. | Typed domain models at every boundary, one module per pipeline stage, one repository per aggregate, and one engine per process. Keep modules focused (about 400 lines is the warning sign). |
| 4 | An in-process APScheduler with a hand-written startup catch-up window, running on a VPS the owner must maintain. If the box was down, the briefing was missed. | No server. A scheduled GitHub Actions workflow runs the daily cycle as a one-shot job, with two staggered triggers and an idempotent claim per `(owner, briefing_date)`. A late or dropped trigger never means a missed or duplicate briefing, and a dead-man's switch alerts the owner if nothing was sent. Commands go through a serverless Telegram webhook (Section 17). |
| 5 | A position is one entry price and quantity: no partial sells, fees, dividends or splits. USD and MYR are never combined. | A transaction ledger with FIFO lots, realised and unrealised P&L, dated FX conversion to base currency MYR, and exposure by currency, asset class and concentration (Section 12). |
| 6 | Holdings are never reviewed: thesis status is always `UNASSESSED`, and REDUCE/EXIT exist only as vocabulary. | Deterministic holding-review rules that produce HOLD / REVIEW / REDUCE / EXIT with reason codes (Section 9.4). |
| 7 | Muddled scorecard: a T1 touch counts as a "win" even when the trade later stops out, calibration buckets depend on a `confidence_score` that is never set, the sample is the last N signals rather than a time window, and the sample size is easy to miss. | Named metrics with written definitions, an explicit exit model, a time window, the sample size shown, small samples suppressed, and bootstrap confidence intervals. No confidence scores (Section 11). |
| 8 | yfinance (unofficial) is the primary source for almost everything, including crypto daily bars. Most symbols are single-source. | A provider adapter per source, with a primary and cross-check provider per symbol. Crypto daily bars come from an exchange candles API. Single-source symbols are labelled `single_source`, and provider health is tracked (Section 8). |
| 9 | Prices are rounded to 4 decimals, which made entry, T1 and T2 collapse for low-priced assets. Money is held as float. | `Decimal` for money and prices, quantised to each instrument's tick size. Floats appear only inside indicator maths. |
| 10 | No way to ask "why no setup?". `/history` lists delivery summaries, not the saved briefings. | Every decision, including rejections, records reason codes. Add `/why TICKER`, and `/briefing DATE` to re-render a saved briefing. |
| 11 | Missing DB constraints: no uniqueness for a signal's daily identity, and active-position uniqueness enforced only in Python. | Constraints and partial unique indexes live in the schema, and invariants are tested against real PostgreSQL. |
| 12 | Backups are written straight to their final name, and verification chooses a backup by mtime with no age limit. | Write to a temp file, fsync, checksum, then rename atomically. Enforce maximum-age gates and run restore drills automatically (Section 17). |
| 13 | No Python lint or type check, runtime requirements include test tools, and README commands differ from CI. | uv dependency groups, ruff, strict mypy, and one `check` task that CI runs verbatim. |
| 14 | The showcase has four overlapping stylesheets (about 143 KB) on top of Tailwind. Essential content stays hidden until hydration. Hand-written fictional fixtures drifted from the backend maths. | One design-token source and content that renders without JavaScript. Demo data is **generated by the real Python pipeline** from a synthetic market fixture, so it cannot drift (Section 20). |
| 15 | Committed `.patch` files, a 95 KB code dump, 15 phase documents, and three project names (InvestGPT, ai-finance-advisor, Goldirham Lens). | One name. ADRs, one runbook, a changelog and release notes. Verification evidence lives in CI artifacts and release notes. |

---

## 4. Scope

**In scope for v2.0**

- Daily briefing (Telegram), with market context, portfolio, holding reviews, changes since the last briefing, new setups (0 to 3) and updates on open signals.
- A watchlist covering crypto, US stocks/ETFs and Bursa Malaysia stocks.
- A data-quality pipeline, readiness reporting, and backfill.
- A strategy engine, a backtest/walk-forward engine, and signal tracking with a scorecard.
- A portfolio transaction ledger with FX conversion to MYR.
- Close-based alerts on holdings (for example, "closed below the review stop"), delivered after the session closes and deduplicated.
- Optional AI narrative, off by default.
- Serverless operations: scheduled GitHub Actions workflows, a dead-man's switch, backups, restore drills, health checks, an owner alert for each failure.
- A public, read-only showcase website with a full motion system: motion background, motion graphics and interface animation (Section 20.1).

**Non-goals**

- Order execution, broker connections, API keys with trading permission.
- Intraday or real-time alerts. Every alert is based on a completed daily close.
- Leverage, derivatives, options.
- Sentiment as a trigger. Sentiment is context only.
- Forced daily recommendations.
- Multi-user SaaS, and public redistribution of market data.

---

## 5. Tech stack

Use the latest stable release of each tool at build time and pin exact versions in lockfiles. Check every external API, SDK and CLI flag against its current official documentation before you write code for it, because APIs drift.

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.13 | Modern typing; async end to end. |
| Packaging | `uv` with `pyproject.toml`, `uv.lock`, and dependency groups `dev` / `test` / `ops` | Reproducible installs; runtime separated from tooling. |
| Tasks | `poethepoet` tasks in `pyproject.toml` (`uv run poe check`) | One cross-platform command, the same on Windows and in CI. |
| Lint / format / types | ruff (lint and format), mypy `--strict`, import-linter | Catches the class of bugs v1 found only in review. Enforces layering. |
| Domain types | pydantic v2 (frozen models at boundaries) and `dataclasses` inside the domain | Explicit contracts. |
| Settings | pydantic-settings (secrets from env) and a YAML file for product settings, validated at startup | Fail fast on bad config. |
| Database | Managed PostgreSQL: Supabase free tier by default, Neon as the alternative (pick in an ADR). SQLAlchemy 2 async with asyncpg, Alembic. | No server to run. The webhook uses the pooled (transaction-mode) connection string with asyncpg's prepared-statement cache disabled. The daily job and migrations use the direct or session connection. |
| HTTP | httpx (async) and a small retry helper with jittered backoff | One client per provider, connection reuse. |
| Calendars | `exchange_calendars` | XNYS and XKLS sessions. |
| Numerics | numpy and pandas (or polars) inside indicator code only, with in-house RSI, ATR, SMA, EMA, MACD and Bollinger implementations | Drop the `ta` dependency. Verify against frozen reference vectors. |
| Telegram | python-telegram-bot (v22+) used as a library: Bot API calls for the daily send, and update parsing in webhook mode | Daily push needs no listener. Commands arrive as webhooks verified with Telegram's `secret_token` header. |
| CLI | Typer: `lens cycle`, `lens replay`, `lens backtest`, `lens backfill`, `lens readiness`, `lens doctor`, `lens demo export` | Every operation is scriptable and testable. |
| Logging | structlog JSON to journald, with redaction of secret patterns **and the exact configured secret values** | v1 redacted patterns only. |
| AI (optional) | Official `anthropic` Python SDK (async), structured outputs | See Section 16. |
| Tests | pytest, pytest-asyncio, Hypothesis, respx (recorded HTTP), testcontainers or the CI Postgres service, syrupy (golden files) | |
| Security | gitleaks (pre-commit and CI), pip-audit on the exported lock, `npm audit`, Dependabot or Renovate weekly | |
| Frontend | Next.js (App Router), React, TypeScript strict, Tailwind v4 with one `@theme` token file, Vitest + Testing Library, Playwright + axe-core | |
| Motion | Motion (motion.dev) for UI and scroll-linked animation; WebGL2 (raw or OGL) for the motion background, with a Canvas 2D fallback; Remotion (optional) for rendered brand loops | One animation library for the UI, a small renderer for the background, and video only where a file is needed (Section 20.1). |
| Daily runner | GitHub Actions scheduled workflow in a **private** repository (cron in UTC, plus `workflow_dispatch`) | Free, no server. Scheduled runs can start late or occasionally be skipped, so Section 17 builds in redundancy. |
| Bot webhook | Vercel Python serverless function (FastAPI), as its own Vercel project separate from the showcase | Answers commands with no always-on process. |
| Dead-man's switch | Healthchecks.io (free) | Alerts the owner when no successful run has pinged by the deadline, including the case where GitHub never started the job. |
| Local development | Docker Compose with Postgres 17 on loopback | Matches the managed Postgres major version. |

Development happens on **Windows 11 with PowerShell 5.1**: no `&&`, use `npm.cmd`. Every documented command must work there and in Linux CI.

---

## 6. Repository layout

```text
src/lens/
  domain/          pure, no I/O: instruments, sessions, money/ticks, bars, indicators,
                   strategy/, risk, holdings, evaluation, scorecard, facts, reasons
  data/            provider adapters, quality checks, corporate actions, FX, backfill
  storage/         SQLAlchemy models, one repository per aggregate, unit of work
  pipeline/        stages: collect -> validate -> analyze -> decide -> compose -> narrate -> deliver
                   plus run/stage records and the idempotent cycle claim
  narrative/       optional AI: fact catalog, prompt, placeholder verifier, budget ledger
  delivery/        Telegram renderer, chunker, delivery state machine
  bot/             command handlers, owner guard, global error handler
  backtest/        replay engine and walk-forward reports (uses domain/ only)
  ops/             doctor, health, alerts, backup status, notifications
  webhook.py       FastAPI app for Telegram updates (imports bot, storage, delivery only)
  cli.py
api/
  telegram.py      Vercel entry point that re-exports lens.webhook:app
.github/workflows/
  ci.yml           the full quality gate on push and PR
  daily.yml        the daily cycle (two schedules + workflow_dispatch)
  backfill.yml     dispatched by /watchlist add, and manually
  backup.yml       nightly encrypted pg_dump
  restore-drill.yml weekly restore into a throwaway Postgres service container
  migrate.yml      manual, gated by the `production` environment's required reviewer
  provider-drift.yml weekly live-provider contract check (non-blocking)
migrations/        Alembic
config/            settings.yaml, strategies/*.yaml
scripts/           backup and restore helpers (shell, checked in CI with bash -n, shellcheck and actionlint for workflows)
tests/             mirrors src/lens/, plus tests/golden/ and tests/fixtures/
web/               public showcase (isolated, never touches backend services)
docs/              ARCHITECTURE.md, STRATEGY.md, RUNBOOK.md, SECURITY.md, adr/NNNN-*.md
AGENTS.md          agent conventions; CLAUDE.md contains only "@AGENTS.md"
CHANGELOG.md
```

Enforce these layering rules with import-linter contracts:

- `domain` imports nothing from the other layers.
- `backtest` imports only `domain`.
- `bot`, `delivery` and `webhook` never import `data`, `backtest`, numpy or pandas. This keeps the serverless webhook small and quick to cold-start.

---

## 7. Domain contracts

Define these types first. They are the contracts between stages. Each stage takes and returns typed objects, never loose dicts.

- **Instrument**: symbol, display name, market (`XNYS`, `XKLS`, `CRYPTO_UTC`), asset class (`crypto` / `stock` / `etf`), quote currency, tick-size rule, provider mapping, and the benchmark to use.
- **Session**: market, date, open and close in UTC, and `is_closed(now)`.
- **RawBar**: one row per provider per instrument per session: unadjusted OHLCV as `Decimal`, provider, `fetched_at`, payload hash.
- **CorporateAction**: split or dividend, with effective date, ratio or amount, source and status (`confirmed` / `pending_review`).
- **Bar** (canonical): the chosen raw bar plus the adjustment factor derived from confirmed actions, a quality status (`verified` / `single_source` / `disputed` / `suspect` / `quarantined`), and its provenance.
- **Readiness**: `ready`, or one or more reason codes.
- **IndicatorSet**: values with the number of sessions used, computed only from a `MarketView`.
- **MarketView**: a read-only view of bars up to and including an `as_of` session. Any access past `as_of` raises, which is how no-look-ahead is enforced in both live and backtest runs.
- **MarketRegime**: benchmark trend state, breadth (the share of the watchlist above its MA200), crypto Fear & Greed as context.
- **StrategyParams**: frozen pydantic model. `strategy_version = sha256(canonical_json(params) + strategy_code_version)[:12]`.
- **Decision**: instrument, session, strategy version, `eligible`, an ordered `reasons: list[ReasonCode]`, and an optional `Setup`.
- **Setup**: entry, stop, T1, T2 (`Decimal`, tick-quantised), R unit, reward:risk, position size (% of equity, and quantity when equity is known), method string.
- **HoldingReview**: action (`HOLD` / `REVIEW` / `REDUCE` / `EXIT`), reasons, and the reference levels used.
- **Signal** and **SignalEvent**: an immutable signal plus an append-only event history (`ACTIVATED`, `T1_TOUCHED`, `STOPPED`, `T2_HIT`, `EXPIRED`, `PAUSED_DATA_GAP`, `UNVERIFIABLE`).
- **Transaction** (`BUY`, `SELL`, `FEE`, `DIVIDEND`, `SPLIT`, `TRANSFER_IN`, `TRANSFER_OUT`), **Lot**, **PortfolioSnapshot**.
- **FxRate**: pair, rate date, rate, source.
- **Fact**: ID, scope (`market` / `holding` / `setup` / `portfolio`), subject, metric, `Decimal` value, unit, session date, source, status.
- **BriefingDocument**: the typed structure the renderers consume (Section 13).
- **DeliveryRecord**: state, chunks, Telegram message IDs, attempts, error class.

**ReasonCode** is a `StrEnum` of stable, documented strings, for example `insufficient_history`, `stale_session`, `missing_session`, `disputed_bar`, `suspect_bar`, `corporate_action_pending`, `single_source_unverified`, `unsupported_market`, `trend_filter_failed`, `below_floor`, `volatility_too_high`, `no_pullback_trigger`, `reward_risk_below_minimum`, `fundamentals_excluded`, `precision_too_coarse`, `concentration_cap_reached`. Each code has a plain-English label in one place, used by `/why`, `/readiness`, the briefing and the website.

---

## 8. Data layer

### 8.1 Providers

Each provider sits behind a `BarProvider` protocol: `async fetch_daily(instrument, start, end) -> list[RawBar]`. Map providers per symbol in config. Before using any provider, check its current terms of use and rate limits and record them in an ADR.

| Market | Primary | Cross-check | Notes |
|---|---|---|---|
| US stocks/ETFs | Yahoo Finance via yfinance (unofficial; label it) | Alpha Vantage, Tiingo, or Stooq (pick one in an ADR) | Cross-check tolerance is 2% on the same session close. Budget free-tier calls. |
| Bursa Malaysia | Yahoo Finance (`.KL`) | None free and reliable | Mark these symbols `single_source` and disclose that in the briefing. |
| Crypto | An exchange's public daily candles (for example Coinbase Exchange or Kraken), with the session defined as 00:00–24:00 UTC | CoinGecko | v1 pulled crypto daily bars from Yahoo. Use an exchange as primary instead. |
| FX (USD/MYR and others) | Bank Negara Malaysia Open API exchange rates | ECB reference rates (via Frankfurter or the ECB directly) | Store the rate date and source. Never convert without a dated rate. |
| Fundamentals (stocks only) | Yahoo (cached, refreshed weekly) | None | Keep timestamps per asset. A fetch that returns nothing usable is a failure, never "fresh empty". |
| Context | Alternative.me crypto Fear & Greed, business RSS headlines | None | Treat this as data only. Headlines never become claims. |

Track provider health per source in the database: success rate, latency p95, the last error class. `/health` shows it.

### 8.2 Validation rules (for each raw bar)

1. The session exists in the market calendar and has closed (`session_close <= now`).
2. All values are finite, `low > 0`, `volume >= 0`, and `low <= min(open, close) <= max(open, close) <= high`.
3. Jump check against the previous close: more than 20% for stocks or 35% for crypto, without volume confirmation, is `suspect`.
4. When two providers disagree on the close by more than the tolerance, the bar is `disputed` and quarantined from setups. The secondary never silently replaces the primary.
5. A move matching a split ratio (2:1, 3:1, 1:2, 3:2 within 1%) with no confirmed action is `corporate_action_pending` and quarantined until resolved.
6. Store raw bars **unadjusted** and derive adjusted series from confirmed corporate actions, so adjustments are recomputable and auditable.

### 8.3 Readiness and backfill

- An asset is `ready` when its last N sessions (default 200) are contiguous, closed, verified (or `single_source` where allowed), and the newest one is the latest closed session.
- Adding an asset (`/watchlist add`) dispatches `backfill.yml` through the GitHub API. The bot replies right away ("backfill started"), and the workflow sends a follow-up message with `ready` or the reason codes once it finishes.
- Watched assets **and** held assets are always collected. A holding is never left without prices.
- Collect with bounded concurrency per provider (a semaphore per provider, plus rate-limit budgets). Every request has a timeout and work cannot be orphaned: use a `TaskGroup` with cancellation.

---

## 9. Analysis, strategy and holding reviews

### 9.1 Indicators

SMA 20/50/200, EMA 12/26, MACD (12, 26, 9), RSI 14 (Wilder), ATR 14 (Wilder), Bollinger (20, 2), 52-week high/low, swing highs and lows (fractal radius from config), realised volatility (20-session), relative strength versus the benchmark (SPY for US, FBM KLCI or a configured proxy for Bursa, BTC for crypto).

Implement each one in-house as a pure function over a `MarketView`. Freeze reference vectors computed once from an established library and assert against them to 1e-9.

### 9.2 Strategy interface

```python
class Strategy(Protocol):
    name: str
    params_model: type[StrategyParams]
    def decide(self, view: MarketView, ctx: AssetContext, params: StrategyParams) -> Decision: ...
```

Strategies are pure, deterministic and registered by name. Each reason it emits is a `ReasonCode`.

**`pullback_in_uptrend`** reproduces v1's defaults exactly. It is the baseline.

- At least 200 verified sessions.
- Trend: `MA50 > 1.05 × MA200`.
- Floor: `close >= 0.85 × MA200`.
- Volatility: `ATR14 / close <= 8%`.
- Trigger: `RSI14 < 25`, **or** close within 1% of the most recent swing low (fractal radius 2).
- Fundamentals (stocks only, when available): exclude P/E ≤ 0 or > 100, and revenue growth below −20%.
- Setup: `stop = close − 2 × ATR14`; `T1 = entry + 1.5R`; `T2 = entry + 3R`; reward:risk must be ≥ 2.0.
- Sizing: `size% = min(max_position_pct, risk_per_trade_pct / stop_distance%)`.
- After tick quantisation, require `stop < entry < T1 < T2`; otherwise the reason is `precision_too_coarse`.

**`breakout_52w`** is an example of a second strategy: close above the prior 52-week high with volume above 1.5× its 50-session average. It ships `enabled: false` with the label "research only" until it has a walk-forward report.

### 9.3 Risk

- Use the owner's equity in MYR (Section 12) to turn size% into a quantity. When equity is unknown, show % only.
- Enforce caps per position and per asset class (for example, crypto at most 30% of equity). Hitting a cap is a reason code, never a silent resize.
- Every setup carries the note: "gaps can exceed the planned stop."

### 9.4 Holding reviews (new)

These run daily for every holding, from completed sessions only:

- `EXIT` when the close is below a chandelier stop (highest close since entry − 3 × ATR14, configurable), **or** the close has been below MA200 for N consecutive sessions (default 3).
- `REDUCE` when the position is above the concentration cap at the current mark.
- `REVIEW` when drawdown from the post-entry peak is beyond a threshold (default 25%), or the data is stale, disputed or single-source for more than K sessions.
- `HOLD` otherwise.

Reviews are suggestions with reasons and reference levels, never instructions. A change in review state can trigger a close-based alert (Section 15).

---

## 10. Backtest and walk-forward (new)

- `lens backtest --strategy NAME --params FILE --from DATE --to DATE` replays canonical bars session by session through the **same** `MarketView` → `decide` → evaluation code that live runs use.
- Execution assumptions are explicit and stored in the report: entry at the next session open or at the signal close (pick one in an ADR; the default is next open); stop-first when one bar touches both stop and target; a gap through the stop fills at the open; no fees by default, with configurable fees and slippage.
- Walk-forward: rolling in-sample and out-of-sample windows. Tune only in-sample. The headline is out-of-sample.
- Baselines in every report: buy-and-hold of the instrument and its benchmark, and random entries with the same holding-period distribution (seeded, many runs).
- Report (Markdown and JSON, saved under `reports/` and stored in the database): trades, hit rates, expectancy in R with a bootstrap 90% CI, max drawdown in R, exposure time, distribution of R, per-asset and per-market splits, and a caveat block (survivorship: the watchlist was chosen today; small sample; data-quality exclusions).
- Determinism: the same inputs give a report with the same hash. Test this.
- Activation gate: `lens strategy activate NAME VERSION` refuses to run unless a report exists for that exact `strategy_version`. The live cycle uses only the active versions.

---

## 11. Signal tracking and scorecard

- A signal activates at the session after it is generated (the same rule as the backtest). Evaluate open signals over each newly closed session in order, using a cursor, and stop at data gaps or disputes (`PAUSED_DATA_GAP`).
- Expiry is configurable (default 120 calendar days). A signal that cannot be evaluated after expiry plus a grace period becomes `UNVERIFIABLE` and is excluded from rates but counted and disclosed.
- **Exit model** is explicit and named in every output. The default, `full_to_t2`, holds the full position to stop, T2 or expiry. The alternative, `half_at_t1_breakeven`, is reported alongside it.
- Metrics, each with a one-line definition shown in `/scorecard` and on the website:
  - T1-touch rate
  - Terminal win rate (final R > 0)
  - Expectancy (mean R) with a 90% bootstrap CI
  - Median holding period
  - MFE/MAE quartiles
  - Open, unverifiable and legacy-excluded counts
- Window: the last 365 days, plus all-time. Always show n. When n < 20, show counts only and "insufficient sample".
- Never show confidence scores.

---

## 12. Portfolio ledger and FX (new)

- `/buy`, `/sell`, `/fee`, `/dividend` and `/split` write `Transaction` rows, and positions are derived from them. Lots are FIFO. A partial sell realises P&L on the lots it consumes. Fees go into cost basis (buys) or reduce proceeds (sells).
- Marks use the latest verified completed close, with session date, source and freshness. A missing mark is `unavailable`, never the entry price.
- The base currency is MYR. Convert with the FX rate dated on or before the mark session and show the FX date. Without a rate, show the position in its own currency and exclude it from the MYR total, with a note saying so.
- The portfolio view shows: total value (MYR), unrealised and realised P&L, day change, exposure by asset class, currency and position, the concentration flags, and each holding's review state.
- `/journal` lists closed lots and transactions, and lets the owner attach a thesis note to a position. Thesis notes stay private and are never sent to AI unless the owner opts in.

---

## 13. Briefing composition and Telegram rendering

`compose` builds a typed `BriefingDocument`. Renderers are pure functions of that document: Telegram HTML, plain text, and JSON for the website demo.

Section order (empty sections collapse into a single line):

1. **Header**: date and time (MYT), the data-as-of session per market, the mode (`deterministic` / `narrated`).
2. **Data status**: one line when everything is healthy. Otherwise, list the degraded sources and assets with reasons.
3. **Portfolio**: MYR total with FX date, day change, holdings with mark status. `EXIT` and `REDUCE` reviews come first.
4. **What changed**: material moves (≥ 2%), new and removed setups, review-state changes, signal events since the last briefing.
5. **New setups**: zero to three, ranked by a deterministic score. Each shows entry, stop, T1, T2 with % distances, size, reasons, invalidation, and a provenance line.
6. **Open signals**: T1 touches, stops, expiries.
7. **Market context**: regime, benchmark moves, crypto Fear & Greed, up to five headlines (title and source only).
8. **Narrative**: only when enabled and verified (Section 16).
9. **Footer**: disclaimer, strategy versions, briefing ID, `/why TICKER` hint.

Rendering rules:

- Telegram HTML parse mode, with every dynamic value escaped by one shared helper.
- Split into chunks at section boundaries, each at most 4,096 characters. Never split inside a tag.
- `detail: concise | detailed` is a per-owner preference.
- Golden-file tests cover every scenario in Section 23.

---

## 14. Delivery state machine

```
PENDING -> COMPOSED -> CLAIMED -> SENDING -> SENT
                                   |-> HELD    (ambiguous: timeout/network after a chunk may have been delivered)
                                   |-> FAILED  (definite: 400/403 before any chunk was accepted; retry allowed)
HELD -> RESENT (owner action, audited) | DISMISSED
```

- A claim token is written in the same transaction as the state change. Uniqueness per `(owner_id, briefing_date)` makes a second cycle exit cleanly.
- Persist each chunk's `message_id` as soon as Telegram accepts it. On resume, send only the chunks that were not accepted.
- On 429, honour `retry_after` within a total send deadline. Errors are classified as definite, ambiguous or rate-limited, and sanitised before they are stored.
- `/held` shows a held briefing's preview and offers inline buttons: **Resend remaining chunks** or **Dismiss**. Each button acts once, and the action is recorded with a timestamp.
- Database outage: the runner has no persistent disk, so it builds a **degraded briefing statelessly**. It fetches enough history from the providers to compute market context and setups, marks portfolio and tracking as unavailable, labels the briefing "degraded: database unreachable", and sends it once. Because the database claim is unavailable, degraded mode uses a per-date marker in the GitHub Actions cache (`degraded-sent-YYYY-MM-DD`) as its idempotency ledger. It still pings Healthchecks `/fail`, so the owner knows to look.

---

## 15. Telegram bot

**Runtime.** The bot is a webhook on a Vercel Python function. Nothing runs between messages.

- Register it once with `setWebhook`, passing a random `secret_token` and `allowed_updates` limited to messages and callback queries.
- Reject (401) any request whose `X-Telegram-Bot-Api-Secret-Token` header does not match, before parsing the body or touching the database.
- Handlers only read and write the database and render text. They answer within a few seconds.
- Anything heavy (backfill, backtest, an on-demand cycle) is handed to a GitHub Actions workflow through `workflow_dispatch`, using a fine-grained token scoped to this one repository with Actions write access. The result arrives later as its own Telegram message.
- `/why` reads the decision record the daily cycle persisted, including reasons and the indicator values used. It never recomputes.

**Guard.** Every handler goes through one owner guard: the user ID must match, the chat must be private, and the chat ID must equal the user ID. A test lists the registered handlers and fails when one is unguarded. A global error handler replies with a short, sanitised message plus an error ID that matches the log entry.

**Independence.** The daily briefing does not depend on the webhook. If Vercel is down, the morning message still arrives.

| Command | Purpose |
|---|---|
| `/today` | The latest briefing (re-rendered from storage). |
| `/briefing DATE` | A saved briefing for that date. |
| `/why TICKER` | The latest decision for that asset: readiness, indicators with provenance, each rule pass/fail, the setup or rejection reasons, and the holding review. |
| `/readiness [TICKER]` | History eligibility and reasons. |
| `/portfolio` | Holdings, MYR totals, exposure, reviews. |
| `/buy`, `/sell`, `/fee`, `/dividend`, `/split` | Ledger entries, each confirmed with an inline button before it is written. |
| `/journal` | Transactions, closed lots, thesis notes. |
| `/watchlist [add/remove TICKER]` | Manage the watchlist. Adding one starts a backfill. |
| `/scorecard` | Metrics with definitions, window, n, CI. |
| `/strategy` | Active versions, parameters, latest backtest summary. |
| `/alerts` | Configure close-based holding alerts: thresholds, quiet hours, digest or immediate. |
| `/held` | Review held deliveries. |
| `/usage` | AI ledger: reserved, settled, unknown, budget remaining. |
| `/health` | On-time rate over the last 7 and 30 days, last run stage timings, provider health, backup age, last restore drill. |
| `/preferences` | Risk %, detail level, alert settings. |
| `/feedback useful/quiet/noisy [note]` | Rate the latest briefing. |
| `/privacy`, `/help`, `/start` | Data handling, help. |

Validate every command argument with pydantic: finite numbers, known tickers, bounded lengths. Bound and chunk long replies.

---

## 16. Optional AI narrative

This is off by default. It adds a short plain-language paragraph without weakening **Python owns the facts**.

**Model and API.** Read the current Anthropic documentation (or the `claude-api` skill) before you write this module.

- Default model: `claude-opus-5-5`. The owner may switch to `claude-haiku-5-5` in config to lower cost. Either way the cost is a few US cents per briefing.
- Use `client.messages.parse(...)` with a pydantic `output_format` (structured outputs) and `output_config={"effort": "low"}`. Forced `tool_choice` returns a 400 on current models, and sampling parameters such as `temperature` are not accepted.
- Check `stop_reason` before reading content. On `refusal` or `max_tokens`, fall back to the deterministic briefing.
- Turn off SDK automatic retries and use your own policy: at most one retry, and only when the failure is definite and happened before any tokens were billed.
- Wrap each call in a hard deadline so a narrative can never delay delivery.

**Fact catalog.** Build it only from `ready` data. Each fact has an ID of the form `scope/subject/metric/session`. Quantities, entry prices, account values and thesis notes are left out unless the owner opts in through `/privacy`.

**Output schema** (pydantic, `extra="forbid"`):

```text
market:   list[Sentence]                  (max 3)
holdings: list[{symbol, sentences: list[Sentence]}]   (holding symbols only)
setups:   list[{symbol, sentences: list[Sentence]}]   (setup symbols only)
caveat:   Literal["uncertainty", "position_sizing", "data_quality"]
Sentence: str, max 240 chars
```

**Placeholder grounding verifier.** Run it before any text is used.

1. Only `{{f:<id>}}` placeholders may carry values. After the placeholders are removed, the text must contain no digit, `%`, currency symbol or code, or spelled-out number.
2. Every ID exists, and its scope and subject match the section and symbol it appears under.
3. Banned phrases (imperatives and certainty such as "buy now", "sell", "guaranteed", "will rise", "can't lose") reject the whole output.
4. Limits on sentence count and length hold.
5. Python replaces each placeholder with the formatted value, unit and session. Any failure leads to the deterministic briefing, with the failure class recorded.

**Budget ledger.**

- Before the call, run `messages.count_tokens`. Reserve `input_tokens × input_rate + max_tokens × output_rate` **atomically**, with a row lock or advisory lock on `(owner_id, utc_date)`, against the daily call and USD limits.
- After the call, settle against the reported usage. A reservation whose outcome is unknown stays reserved.
- Rates live in config with a `rates_verified_on` date, which `/usage` shows. A dry run can never make a billable call.

**Prompt injection.** Headlines and all fact contents are wrapped as data, and the system prompt says they are data.

**Evals.** Keep at least 30 recorded cases, including injected headlines, empty catalogs, single-holding cases and adversarial outputs that contain numbers. CI runs the verifier against these recorded model outputs with no network. A live eval run is a manual, approved, recorded action.

---

## 17. Operations (serverless)

### 17.1 Where each job runs

| Job | Runs on | Trigger |
|---|---|---|
| Daily cycle: evaluate open signals, collect, validate, analyze, decide, compose, narrate, deliver | GitHub Actions `daily.yml` | Two schedules, `0 23 * * *` and `40 23 * * *` UTC (07:00 and 07:40 MYT), plus `workflow_dispatch` |
| Backfill for a newly added asset | GitHub Actions `backfill.yml` | `workflow_dispatch` from the webhook, or manual |
| Nightly backup | GitHub Actions `backup.yml` | Schedule |
| Weekly restore drill | GitHub Actions `restore-drill.yml` | Schedule |
| Migrations | GitHub Actions `migrate.yml` | Manual only, behind the `production` environment with the owner as required reviewer |
| Provider drift check | GitHub Actions `provider-drift.yml` | Weekly, non-blocking (opens an issue on failure) |
| Telegram commands | Vercel Python function | Webhook |
| Showcase website | Vercel | Push to `main` |

### 17.2 Making "every single day" reliable

GitHub's scheduled workflows run in UTC and can start late or occasionally be skipped when the platform is busy. Design for that:

1. **Two staggered triggers.** The first run normally sends the briefing. The second run finds the day already claimed (`SENT` or `HELD`) and exits successfully in seconds. If the first run never started or failed before sending, the second one sends the briefing.
2. **One run at a time.** Use `concurrency: { group: daily-cycle, cancel-in-progress: false }`, so overlapping triggers run one after the other and never in parallel.
3. **Idempotent claim.** The database claim per `(owner_id, briefing_date)` (Section 14) is the single source of truth for "already sent".
4. **Dead-man's switch.** A Healthchecks.io check expects a success ping every day by 08:15 MYT. The cycle pings `/start` on begin, the success URL after delivery, and `/fail` on error. When no success ping arrives, Healthchecks alerts the owner through its own Telegram or email integration. This works even when GitHub never ran the job.
5. **Failure alert.** A final `if: failure()` step sends one sanitised Telegram alert with the run URL.
6. **Bounded run.** Set `timeout-minutes: 15` on the job and per-stage deadlines inside it. The narrative stage has the tightest deadline, so delivery never waits on it.
7. **Manual rescue.** `workflow_dispatch` (or `/run` from the bot) triggers an on-demand cycle that obeys the same claim, so it cannot cause a duplicate.

**Free-tier limits (verify current numbers and record them in an ADR):**

- A private repository on GitHub Free has a monthly Actions-minutes allowance. Keep the daily cycle at or under about 5 minutes with dependency caching (`astral-sh/setup-uv` cache), and keep CI lean.
- In public repositories, GitHub disables scheduled workflows after 60 days without repository activity. Keep this repository **private**.
- Free managed Postgres projects can pause after a period of inactivity. The daily cycle's writes keep the project active. `lens doctor` reports when the database is unreachable.
- Vercel's Hobby plan is for personal, non-commercial use, which fits a single-owner tool.

### 17.3 Crypto timing decision (write an ADR)

The UTC daily crypto candle closes at **08:00 MYT**.

- **Default:** use the prior completed crypto session and deliver by 08:00. This is compatible with GitHub schedule delays.
- **Alternative:** schedule after 00:05 UTC to include the just-closed session and accept a later delivery.

Use the chosen rule consistently in the backtest.

### 17.4 Run records and logging

- `pipeline_runs` stores cycle ID, owner, date, trigger (`schedule_1` / `schedule_2` / `dispatch`), GitHub run ID, code version (git SHA), strategy versions, input hash and status.
- `stage_runs` stores stage, start, end, outcome and error class.
- Every log line carries `cycle_id`. Logs go to the Actions log in JSON with redaction applied.
- Each briefing's `BriefingDocument` JSON is also uploaded as a workflow artifact for audit.

### 17.5 Backups and restore drills

1. In `backup.yml`, install a `pg_dump` client that matches the server's major version. Dump with `pg_dump -Fc` to a temp file, write a SHA-256 manifest with per-table row counts and checksums, then age-encrypt with `AGE_RECIPIENT` (a public key).
2. Upload the encrypted dump and its manifest as a workflow artifact (retention set in the workflow), and optionally to S3-compatible storage such as Cloudflare R2.
3. `restore-drill.yml` downloads the newest backup, refuses one older than 26 hours, and decrypts it with the private key, which exists only in that job's secrets. Keep an offline copy of that key too. The drill restores into a **Postgres service container inside the job** and compares row counts and checksums with the manifest.
4. The drill target is always the job-local container. A guard parses and decodes the target URL and refuses anything that is not `localhost` with the drill's database name.
5. The drill reports its result to Healthchecks and to the owner on failure. `/health` shows the last backup age and the last drill result.

### 17.6 Migrations

Only `migrate.yml` changes the production schema. It is manual and needs the owner's approval in the GitHub `production` environment, and it takes a fresh backup first. The daily cycle checks that the database revision equals the code's Alembic head. On a mismatch it refuses to write, sends a degraded briefing (Section 14), and alerts the owner.

### 17.7 `lens doctor`

`lens doctor` runs locally or through `workflow_dispatch`. It checks:

- config validity
- database connectivity, both direct and pooled
- migration revision against head
- provider reachability
- Telegram `getMe`, and `getWebhookInfo` (URL set, no recent delivery errors)
- Healthchecks reachability
- last backup age and last drill result

It exits non-zero on any failure and prints a readable table.

### 17.8 SLOs

Measure these and show them in `/health`:

| Measure | Target |
|---|---|
| Briefing delivered by 08:00 MYT | ≥ 97% over 30 days |
| Days with no briefing at all | 0 (the Healthchecks alert fires before anyone has to notice) |
| Briefings using the degraded fallback | ≤ 5% |
| Verifier leaks (numbers in narrative) | always 0 |
| Daily run duration p95 | < 5 min |
| Monthly AI spend | below the configured cap |
| Monthly hosting cost | USD 0 (free tiers) |

---

## 18. Security and privacy

- Secrets live in GitHub Actions secrets (for workflows) and Vercel environment variables (for the webhook). Each workflow and function gets only the secrets it needs. Secrets never appear on command lines, in logs, in the repo or in fixtures. Workflows never `echo` them, and redaction masks them as well.
- Workflow hardening: top-level `permissions: contents: read` and raise per job only where needed. Pin third-party actions to commit SHAs. Never use `pull_request_target`. Scheduled and dispatch workflows run only on `main`.
- The webhook's GitHub token is fine-grained, scoped to this one repository, with Actions write access only.
- Database roles: `lens_app` (DML on application tables only, used by the daily job and the webhook), `lens_migrator` (DDL, used only by `migrate.yml`), `lens_backup` (read-only). The app role cannot drop or truncate. Enable row-level security, or revoke public access, so the provider's auto-generated APIs (such as Supabase's) cannot read the tables.
- gitleaks runs in pre-commit and CI. Dependency audits run in CI, and dependency PRs arrive weekly.
- AI requests contain only the fact catalog (Section 16). `/privacy` states exactly what leaves the server.
- The website has strict security headers and CSP, no secrets, and no network path to backend services.

---

## 19. Testing and quality gates

`uv run poe check` runs exactly what CI runs:

1. `ruff format --check`, `ruff check`, `mypy --strict src tests`, `lint-imports`.
2. `pytest`: unit tests, Hypothesis properties, golden files, recorded provider contracts, and PostgreSQL integration (testcontainers locally, a service container in CI). Without Docker, integration tests **fail with a clear message** instead of skipping silently. An explicit `--no-db` flag lists what was not run.
3. Migrations: `alembic upgrade head`, `alembic check` (no drift), and a downgrade/upgrade round trip on an empty database.
4. `gitleaks`, `pip-audit` (on the uv export), `bash -n` plus `shellcheck` on scripts, and `actionlint` on every workflow.
5. Coverage gates: `domain/` ≥ 95% lines, overall ≥ 85%.
6. Frontend (in `web/`): lint, typecheck, Vitest, build, Playwright (Chromium desktop and WebKit mobile), axe (no serious or critical violations), the three-mode motion runs and motion budget checks (Section 20.1), a demo-export freshness check, and `npm audit --audit-level=moderate`.

Required property tests:

- After quantisation, `stop < entry < T1 < T2`, size ≤ cap, and `size% × stop distance% ≤ risk%`, across prices from 0.00001 to 1,000,000.
- A `MarketView` never exposes a bar after `as_of`.
- Evaluation is deterministic, and stop-first resolves bars that touch both stop and target.
- FIFO lot maths conserves quantity and cost.
- The rendered output never exceeds 4,096 characters per chunk, and all dynamic text is escaped.

Required concurrency tests (real PostgreSQL):

- Two cycles racing produce one briefing.
- Two AI reservations racing never exceed the budget.
- Two `/held` resends racing resend at most once.

A weekly, non-blocking CI job hits the live providers to detect API drift and opens an issue when one fails.

---

## 20. Showcase website (`web/`)

- One page, statically generated where possible, deployed to Vercel. It never connects to PostgreSQL, Telegram, Anthropic, the webhook or GitHub Actions.
- **Generated demo data:** `lens demo export` runs the real pipeline in replay mode over a seeded synthetic market fixture and writes `web/data/demo.json`: a briefing document, the Telegram render, portfolio, scorecard and backtest summary. Every value carries a visible **DEMO DATA** label. CI regenerates the export and fails if it differs from the committed file.
- **One token source:** a Tailwind v4 `@theme` file with the brand palette and type scale, fonts loaded through `next/font`, and one global stylesheet.
- **Content renders without JavaScript.** Motion (Section 20.1) is a layer on top of a page that already works without it. It can be paused, and it gets gentler under `prefers-reduced-motion`.
- Sections:
  - Hero ("Numbers before narrative.") over the motion background
  - Sample briefing (the actual Telegram render), with the day switcher
  - How a briefing is made (the pipeline scroll sequence)
  - Method: the rules and reason codes, generated from `STRATEGY.md`
  - Provenance and data quality
  - Scorecard definitions with the demo backtest
  - Reliability practices (labelled as practices, not live status)
  - FAQ and disclaimer
- Claims stay literal. "Every number is computed in Python" is fine. Absolute guarantees and live-looking status indicators stay out.
- Budgets, measured **with the motion layer on**: Lighthouse performance ≥ 95, accessibility 100, nothing scrolls sideways at 360 px, and keyboard navigation and focus states are tested.

### 20.1 Motion system: motion graphics, motion background, animation

Motion is part of the brand. It shows cause and effect the way the product works: data arrives, gets checked, and becomes a result. It is slow and calm in the background and crisp in the interface, and it never bounces. Mint appears in motion only at the moment something is verified.

**Rules**

- **Motion never shows a false number.** Every figure appears at its final value. Animate position, opacity, clip and stroke; never count a figure up through values that were never true.
- **Static first.** Build the complete page without motion (Phase 11), then add motion as a layer (Phase 12). With the layer switched off by its flag, the page still passes every Phase 11 gate.
- Animate `transform`, `opacity`, SVG `stroke-dashoffset` and `clip-path` only. Name properties explicitly, never `transition: all`. No animation may cause layout shift.
- Easing follows the `animate` skill's tables:
  - `ease-out` for anything entering or exiting
  - `ease-in-out` for movement on screen
  - `linear` for constant motion such as the ticker
  - never `ease-in`, bounce or elastic
- Exits are faster than entries. Entrances start from `scale(0.95)` plus `opacity: 0`, never `scale(0)`. Groups stagger by 30–80 ms instead of arriving all at once.
- Hover motion only under `@media (hover: hover) and (pointer: fine)`.
- **One motion-token source**, in the same `@theme` file as colour and type:

| Token | Value | Used for |
|---|---|---|
| `--ease-out` | `cubic-bezier(0.23, 1, 0.32, 1)` | entering and exiting |
| `--ease-in-out` | `cubic-bezier(0.77, 0, 0.175, 1)` | movement on screen |
| `--motion-press` | `140ms` | press feedback |
| `--motion-ui` | `200ms` | tooltips, menus, state changes (UI stays under 300 ms) |
| `--motion-reveal` | `280ms` | scroll reveals |
| `--motion-explain` | `600ms` | each step of the hero and pipeline sequences (explanatory motion may run longer) |
| `--stagger` | `60ms` | grouped entrances |

**The pieces**

| Piece | What it does | Built with | Reduced motion and no-JS fallback |
|---|---|---|---|
| **Signal field** (motion background) | A full-viewport layer behind all content: a faint ruled grid with slow-drifting price traces drawn from the demo fixture's synthetic bars, in Fog at low opacity. Every 8–12 s one trace passes through a thin verification frame, turns mint for a moment, then fades back. Gentle parallax on scroll, at most 24 px. One full drift cycle takes 30–60 s. | A WebGL2 shader (raw WebGL2 or OGL), with Canvas 2D as the fallback when WebGL is unavailable | A static SVG poster of the same field, generated at build time from the same fixture |
| **Lens** | A 160–220 px circular lens around the pointer shows the traces sharper, with tiny provenance ticks (session date and source). On touch screens it rests in place and drifts slowly with scroll, so no pointer is needed. | The same shader, with the lens position as a uniform. Pointer input is sampled once per animation frame. | Off |
| **Hero proof sequence** (motion graphic) | Plays once per visit, 1.6 s at most. The mark's frame strokes in, the stepped trace draws and turns mint as it crosses the frame, then "Numbers before narrative." reveals word by word, with "narrative." landing last. | SVG `stroke-dashoffset` and Motion | Final state shown immediately |
| **Pipeline scroll** ("How a briefing is made") | A pinned section driven by scroll position: provider bars slide in, validation marks each bar (one disputed bar shows its reason code and drops out), indicator lines draw, rule checks pass or fail with reason codes, and the Telegram message assembles chunk by chunk. | CSS `position: sticky` with Motion `useScroll`/`useTransform`, or GSAP ScrollTrigger if `pick-ui-library` prefers it. Use one animation library, not both. | A static five-step diagram with the same content, in reading order |
| **Briefing assembly** | When the sample briefing scrolls into view, it arrives section by section, the way Telegram messages land. | Motion, using `--stagger` | Shown complete |
| **Day switcher** | Three demo days: a quiet day, a setup day and a degraded-data day. Switching animates only what changed: setups enter or leave, data status changes colour, holdings re-sort. This shows that "silence is valid". | Motion `layout` and `AnimatePresence`, or the View Transitions API | Instant swap |
| **Charts** | Scorecard and backtest lines draw in once on first view, bars grow from the baseline, and tooltips fade in over `--motion-ui`. | SVG path length and Motion | Static chart |
| **Ticker tape** | A slow, linear marquee of demo symbols with the DEMO label. It pauses on hover and focus. | A CSS transform animation | Static row |
| **Micro-interactions** | Press feedback (`scale(0.97)` over `--motion-press`), hover states on capable pointers only, the mobile menu sheet, and focus rings that never animate away | CSS transitions and Motion | Colour and opacity changes only |
| **Brand loop** (optional) | A 10–15 s loop of the signal field and hero sequence, rendered to MP4/WebM for the README, social cards and the hero poster | Remotion, reusing the same components and fixture | Not applicable |

**Accessibility**

- A visible **Pause motion** toggle in the header stops the signal field, lens, ticker and any loop. The choice persists in `localStorage`, with every read and write wrapped in try/catch. The background moves for more than five seconds, so WCAG 2.2.2 requires this toggle.
- `prefers-reduced-motion: reduce` switches every piece to its fallback column. Reduced means fewer and gentler, not zero: opacity and colour transitions of 150 ms or less remain, and movement goes.
- Nothing flashes more than three times per second (WCAG 2.3.1).
- Decorative canvases are `aria-hidden`.
- Animation never moves, covers or hides keyboard focus.
- Reveal-on-scroll never hides content from visitors without JavaScript. The hidden starting state applies only after hydration adds a `motion-ready` class on `<html>`. CSS scroll-driven animations may be used as progressive enhancement where the browser supports them.

**Performance budgets**

- **Loading:**
  - The LCP element is the headline text, never the canvas.
  - The signal field starts after first paint, through an idle callback, and fades in.
  - Motion JavaScript totals at most 60 KB gzipped. The background renderer is at most 25 KB gzipped, so no three.js.
- **Rendering:**
  - Cap the canvas device-pixel ratio at 2, or 1.5 on small screens.
  - Drop the field to half resolution when frame time exceeds budget.
  - Stop the animation loop when the tab is hidden, when the canvas is off screen (IntersectionObserver), or when the toggle is off.
- **Targets:**
  - At least 55 fps on a mid-range laptop and at least 45 fps under 4× CPU throttling.
  - No long tasks caused by animation.
  - CLS stays 0.

**Tests**

- Playwright renders every section in three modes (default, `reducedMotion: 'reduce'`, JavaScript disabled) and screenshots each one. Content and reading order are identical across modes.
- The pause toggle stops the loop: no animation frames are requested after toggling, and the setting survives a reload.
- A performance trace under 4× CPU throttling asserts the fps and long-task budgets.
- With WebGL unavailable the Canvas 2D fallback renders. With both unavailable the poster renders. Both fallbacks are tested.
- `review-animations`, `improve-animations` and `animation-performance` findings are fixed, or recorded with a reason.

---

## 21. Optional private dashboard (last phase, only if the owner wants it)

- A separate Vercel project, reached only after owner authentication (for example the Telegram Login Widget verified server-side against the owner ID, or Vercel deployment protection), reading through a read-only database role.
- Views: briefing archive, portfolio history, signal explorer, backtest reports, health.
- It is a separate app from the public showcase and never shares credentials with the browser.

---

## 22. Configuration (`config/settings.yaml` starting point)

```yaml
owner:
  timezone: Asia/Kuala_Lumpur
  base_currency: MYR
  # daily.yml runs at 23:00 and 23:40 UTC (07:00 / 07:40 MYT); GitHub cron is UTC-only
  delivery_deadline: "08:00"
  healthcheck_grace_minutes: 15
  detail: concise
risk:
  risk_per_trade_pct: 1.0    # validated 0 < x <= 5
  max_position_pct: 20.0
  max_asset_class_pct: { crypto: 30.0 }
data:
  min_sessions: 200
  cross_check_tolerance_pct: 2.0
  suspect_jump_pct: { stock: 20.0, etf: 20.0, crypto: 35.0 }
  degraded_mode_history_sessions: 260   # history fetched per asset when the database is unreachable
strategies:
  pullback_in_uptrend:
    enabled: true
    params:
      ma_fast: 50
      ma_slow: 200
      trend_multiple: 1.05
      floor_vs_ma_slow: 0.85
      max_atr_pct: 8.0
      rsi_period: 14
      rsi_trigger: 25
      support_distance_pct: 1.0
      swing_radius: 2
      atr_period: 14
      atr_stop_multiple: 2.0
      targets_r: [1.5, 3.0]
      min_reward_risk: 2.0
      expiry_days: 120
      fundamentals: { max_pe: 100, min_revenue_growth_pct: -20 }
  breakout_52w:
    enabled: false           # research only until a walk-forward report exists
holdings:
  chandelier_atr_multiple: 3.0
  exit_below_ma200_sessions: 3
  drawdown_review_pct: 25
alerts:
  mode: digest               # digest | immediate
  quiet_hours: ["23:00", "07:00"]
scorecard:
  window_days: 365
  min_sample: 20
  exit_model: full_to_t2
narrative:
  enabled: false
  model: claude-opus-5-5
  effort: low
  max_calls_per_day: 3
  daily_budget_usd: 0.50
  rates_verified_on: null    # set after checking current pricing
watchlist:
  - { symbol: BTC-USD, asset_class: crypto }
  - { symbol: ETH-USD, asset_class: crypto }
  - { symbol: SOL-USD, asset_class: crypto }
  - { symbol: BNB-USD, asset_class: crypto }
  - { symbol: SPY,     asset_class: etf }
  - { symbol: QQQ,     asset_class: etf }
  - { symbol: AAPL,    asset_class: stock }
  - { symbol: MSFT,    asset_class: stock }
  - { symbol: NVDA,    asset_class: stock }
  - { symbol: 1155.KL, asset_class: stock, name: Maybank }
  - { symbol: 5183.KL, asset_class: stock, name: Petronas Chemicals }
  - { symbol: 1295.KL, asset_class: stock, name: Public Bank }
```

Secrets and environment (listed without values in `.env.example`, which also documents where each one lives):

| Name | Where it lives | Used by |
|---|---|---|
| `DATABASE_URL_DIRECT` | GitHub secret | daily, backfill, backup, migrate |
| `DATABASE_URL_POOLED` | Vercel env | webhook |
| `TELEGRAM_BOT_TOKEN` | GitHub secret and Vercel env | daily send, webhook |
| `OWNER_TELEGRAM_ID` | GitHub secret and Vercel env | owner guard |
| `TELEGRAM_WEBHOOK_SECRET` | Vercel env | webhook header check |
| `GITHUB_DISPATCH_TOKEN` | Vercel env | webhook triggering workflows |
| `HEALTHCHECK_PING_URL` | GitHub secret | daily, backup, restore drill |
| `ANTHROPIC_API_KEY` | GitHub secret | daily, only when narrative is enabled |
| Cross-check provider keys | GitHub secret | daily, backfill |
| `AGE_RECIPIENT` (public key) | GitHub secret | backup |
| `AGE_IDENTITY` (private key) | GitHub secret, restore-drill job only | restore drill |
| `OFFSITE_*` | GitHub secret | backup (optional R2/B2 copy) |

Locally, `.env` supplies the same names for development against the Compose database.

---

## 23. Acceptance scenarios

Each scenario is an automated test, using golden files for the rendered output.

1. **Bursa holiday.** A Malaysian public holiday is not a missing session. Readiness stays `ready`, and the data-as-of date shows the prior session.
2. **US split day.** A 4:1 move with no confirmed action becomes `corporate_action_pending` and produces no setup. Once the action is confirmed, the adjusted history is recomputed and readiness recovers.
3. **Provider disagreement.** A 3% close difference becomes `disputed`. The asset shows its reason in `/why` and is excluded from setups. Holdings show the mark as `disputed` with its date.
4. **Quiet day.** No setups. The briefing says so in one line, and no section is padded.
5. **Database unreachable at cycle time.** The degraded briefing is built from live provider data and sent once, labelled, with portfolio and tracking marked unavailable. The second scheduled run finds the cache marker and sends nothing. Healthchecks receives `/fail`.
6. **Telegram timeout after chunk 2 of 3.** The delivery becomes `HELD` with two message IDs stored. `/held` → Resend sends only chunk 3.
7. **First scheduled trigger never fires.** The 07:40 trigger sends the briefing. When both are skipped, Healthchecks alerts the owner by 08:15, and a manual dispatch sends the briefing with a "late" note. A trigger that starts after the briefing was sent exits in seconds without sending.
8. **AI output contains "rose 5%".** The verifier rejects it, the deterministic briefing is delivered, and the failure class is recorded. The budget is settled from usage.
9. **Holding without an FX rate.** The position shows in USD and is excluded from the MYR total with a note.
10. **Partial sell with a fee.** FIFO realised P&L matches a hand-computed fixture exactly.
11. **One bar touches both stop and T2.** The outcome is `STOPPED` (stop-first), at the open when the bar gapped below the stop.
12. **Low-priced asset** (close 0.000151, ATR 0.000001). The rejection reason is `precision_too_coarse`, never an invalid setup.
13. **Unguarded handler added.** The coverage test fails.
14. **Two cycles started at once.** Exactly one briefing row and one delivery exist.
15. **Restore drill pointed at production by name, percent-encoding, or a query-string trick.** It is refused before any destructive command runs.
16. **Webhook request with a missing or wrong secret-token header.** The response is 401, and nothing is parsed, logged as an update, or read from the database.
17. **Database schema behind the code.** The daily cycle refuses to write, sends the degraded briefing, and alerts the owner to run `migrate.yml`.

---

## 24. Delivery plan

Work in order, and run every phase through the skills loop in Section 25. At the end of each phase, report three things: the commands you ran with their exact output for every exit criterion, the skills that ran with what each found, and the `CHANGELOG.md` update. Record decisions as ADRs.

The owner's first priority is **a Telegram message every day**. Phase 1 delivers a thin but real daily briefing end to end. Every later phase makes that same daily message richer, and it never stops arriving.

| Phase | Deliverables | Exit criteria |
|---|---|---|
| **0. Foundation** | uv project, ruff/mypy/pytest/import-linter config, pre-commit (ruff, gitleaks), `poe check`, `ci.yml`, `compose.dev.yaml` (Postgres 17 on loopback), Alembic baseline, settings loader, structlog with redaction, the required skills installed and pinned (Section 25), `AGENTS.md` + `CLAUDE.md` (`@AGENTS.md`), `PRODUCT.md` + `DESIGN.md`, README, `ARCHITECTURE.md`, ADR-0001 (architecture), ADR-0002 (agent skills with pinned SHAs) | `uv run poe check` passes locally (Windows PowerShell) and in CI. The redaction test proves that a configured secret value never reaches the log output. Every skill in Section 25 is listed as installed in ADR-0002, or reported as not installable with the reason. |
| **1. Daily skeleton** | Private GitHub repo, managed Postgres project with the baseline migration applied through `migrate.yml`, Healthchecks check, `daily.yml` with both schedules, concurrency and the failure alert. A minimal briefing: each watchlist symbol's latest completed close and daily change with source and session date, plus the disclaimer. | A manual dispatch delivers one message to the owner's chat, **sent only after the owner approves this first real send**. A second dispatch the same day exits with "already sent". A forced failure produces exactly one alert and a Healthchecks `/fail`. From here on the owner receives a briefing every morning. |
| **2. Domain core** | Instruments, calendars and sessions, money and ticks, `MarketView`, indicators, setup and risk maths | Reference vectors and property tests pass. The import-linter contract proves `domain/` has no I/O imports. Domain coverage ≥ 95%. |
| **3. Data** | Provider adapters, raw/canonical bars, validation, corporate actions, FX, `backfill.yml` and CLI, readiness | Scenarios 1–3 pass on fixtures. Recorded contract tests pass. `lens readiness` prints correct reasons for a seeded database. |
| **4. Strategy and backtest** | Strategy registry, `pullback_in_uptrend`, reason codes, backtest/walk-forward engine, reports, activation gate | Scenarios 11 and 12 pass. A repeated backtest gives the same report hash. Activating a version without a report is refused. |
| **5. Pipeline and replay** | Storage repositories, run and stage records, idempotent cycle claim, `BriefingDocument`, `lens cycle --dry-run`, `lens replay`. The daily workflow switches to the full pipeline. | Scenario 14 passes. `lens replay` reproduces a stored briefing byte-for-byte. A dry run writes nothing (asserted by row counts). |
| **6. Briefing and bot** | Renderers, chunker, delivery state machine, Vercel webhook, all commands, owner guard, global error handler | Scenarios 4, 6, 7, 13 and 16 pass. Golden files are committed. `getWebhookInfo` shows the webhook set with no recent errors. The `/impeccable audit` and `break-ui` findings on the briefing render are fixed or recorded. |
| **7. Portfolio** | Ledger, lots, FX conversion, exposure, holding reviews, journal | Scenarios 9 and 10 pass. Review rules have hand-computed fixtures for each action. |
| **8. Tracking** | Evaluator, events, scorecard with definitions and CIs | Hand-computed scorecards match exactly. Insufficient samples are suppressed. |
| **9. Operations** | `backup.yml`, `restore-drill.yml`, `migrate.yml` approval gate, `provider-drift.yml`, degraded mode, `lens doctor` | Scenarios 5, 15 and 17 pass. An interrupted backup never becomes selectable. Each simulated job failure produces exactly one owner alert. |
| **10. AI narrative (optional)** | Fact catalog, prompt, verifier, budget ledger, recorded evals | Scenario 8 passes. All recorded evals pass with zero leaked numbers. The budget race test passes. **A live call happens only after the owner approves its cost.** |
| **11. Showcase (static)** | `lens demo export`, the complete Next.js site with no motion, motion tokens defined but unused, Playwright + axe | All frontend gates pass. The JavaScript-disabled render shows the essential content. The export freshness check passes. `/impeccable audit` and `/impeccable critique` pass with their findings fixed. |
| **12. Showcase motion layer** | Every Section 20.1 piece: signal field with lens, hero proof sequence, pipeline scroll, briefing assembly, day switcher, chart draw-ins, ticker, micro-interactions, the Pause motion toggle, all fallbacks. The optional Remotion brand loop. | All Section 20.1 tests pass. The performance budgets hold with motion on. `review-animations`, `improve-animations` and `animation-performance` pass with findings fixed or recorded. With the motion flag off, every Phase 11 gate still passes. |
| **13. Private dashboard (optional)** | Section 21 | Auth and access-boundary tests pass. |

**v2.0 release gate:**

- Phases 0 to 9, 11 and 12 meet their exit criteria. Phases 10 (AI narrative) and 13 (dashboard) are optional.
- Thirty consecutive days of briefings, at least 97% of them delivered by 08:00 MYT.
- One successful restore drill.
- Zero verifier leaks.
- USD 0 hosting cost.
- Docs describe the shipped behaviour, with dated status claims only.

---

## 25. Required skills and workflow

The owner requires these four skill sets. Install them in Phase 0 and use them in every phase. They are third-party instructions, so read each skill's files before installing. Pin each source to a commit SHA and record the SHAs in `docs/adr/0002-agent-skills.md`.

| Source | Install | Used here for |
|---|---|---|
| **pstack** — `github.com/cursor/plugins/tree/main/pstack` | In Cursor: `/add-plugin pstack`, then `/setup-pstack`. In Claude Code or Codex: copy `pstack/skills/*` into the project's skills folder (`.claude/skills/` or `.agents/skills/`) and `pstack/agents/*` into `.claude/agents/`. | Engineering rigour: `/poteto-mode` and its playbooks, the principle skills, `architect`, `tdd`, `interrogate`, `blast-radius`, `benchmark-checklist`, `no-comments`, `unslop`, `technical-writing`, `show-me-your-work` |
| **HumanLayer** — `github.com/humanlayer/humanlayer` (its `.claude/commands` and `.claude/agents`) | Copy `.claude/commands/*` and `.claude/agents/*` into this repo's `.claude/`. | The research → plan → implement → validate loop, and session handoffs |
| **Impeccable** — `github.com/pbakaus/impeccable` | `npx impeccable install --providers=<your harness> --scope=project`, then `/impeccable init` | Design language for the briefing render, bot replies and website: `PRODUCT.md`, `DESIGN.md`, `shape`, `craft`, `critique`, `audit`, `harden`, `clarify`, `animate`, `overdrive`, `polish` |
| **Emil Kowalski skills** — `github.com/emilkowalski/skills` | `npx skills@latest add emilkowalski/skills` | Interface and motion quality: `emil-design-eng`, `animate`, `animation-vocabulary`, `find-animation-opportunities`, `review-animations`, `improve-animations`, `animation-performance`, `break-ui`, `mobile-native`, `pick-ui-library` |

On the owner's machine, copies of these sources may already be vendored under `E:\Workspace\agent-homebase\vendor\` (`cursor-plugins`, `humanlayer-skills`, `impeccable`, `emilkowalski-skills`). When a vendored copy matches the source above, link it with that repository's `scripts/sync.ps1` instead of downloading it again.

### 25.1 Harness notes

- **pstack is written for Cursor.** Its per-role model routing (`/setup-pstack`, Grok and Opus panels), the `poteto-agent` subagent type, and the `cursor-team-kit` skills it calls (`deslop`, `control-ui`, `control-cli`) exist only in Cursor. In another harness:
  - run its playbooks with your own subagents
  - use `unslop` plus `no-comments` where it says `deslop`
  - use Playwright, or your built-in browser, where it says `control-ui`
- **HumanLayer's README says the repository's code is deprecated.** The slash commands and subagents are the parts to use.
  - Use the `_nt` (no-thoughts-directory) variants: `research_codebase_nt`, `create_plan_nt`, `iterate_plan_nt`.
  - Where `implement_plan`, `validate_plan`, `create_handoff` or `resume_handoff` refer to `thoughts/shared/...`, Linear, or `humanlayer thoughts sync`, write to `docs/research/`, `docs/plans/` and `docs/handoffs/` instead, and skip the sync and Linear steps.
- **Impeccable writes `PRODUCT.md` and `DESIGN.md` at the repo root.** Seed `PRODUCT.md` from Sections 1, 2 and 4 of this prompt, and `DESIGN.md` from the brand in Section 3, so the skill starts from this product's facts.

### 25.2 Precedence

The Working agreement (Section 26) overrides any skill instruction. Autonomous, overnight, shipping and babysit playbooks still stop for the owner's explicit approval before each commit, push, merge, deploy, real Telegram send, paid API call, production database change or file deletion.

### 25.3 Per-phase loop

1. **Research.** `/research_codebase_nt` on the area the phase touches (Phase 0 has nothing to research). Save the result to `docs/research/`.
2. **Plan.** `/create_plan_nt` writes `docs/plans/phase-N-<slug>.md`: deliverables, and success criteria split into **automated** checks (commands) and **manual** checks (owner), copied from Section 24. Use `/iterate_plan_nt` when the owner gives feedback.
3. **Implement.** Run `/poteto-mode` with the matching playbook (feature, refactoring, bug fix, perf, multi-phase plan), or `/implement_plan docs/plans/phase-N-<slug>.md`. Inside it:
   - `architect` before code that crosses a module boundary: stage contracts, repositories, the provider protocol, the webhook.
   - `tdd` for domain maths, state machines, the verifier, and every bug.
   - The principles, especially `model-the-domain`, `make-operations-idempotent`, `fix-root-causes`, `prove-it-works`, `type-system-discipline`, `boundary-discipline` and `laziness-protocol`.
   - `benchmark-checklist` before reporting any performance number (daily run duration, webhook cold start).
4. **Validate.** `/validate_plan` against the plan's success criteria, with command output pasted verbatim.
5. **Review the diff.**
   - `blast-radius` for small-looking changes to shared code.
   - `interrogate` for contested designs: the delivery state machine, the budget ledger, the backtest execution model.
   - `no-comments` before review.
6. **Prose.**
   - `unslop` on every owner-facing string: briefing copy, bot replies, website text.
   - `technical-writing` for README, ADRs, the runbook, `CHANGELOG.md` and PR descriptions.
7. **Hand off.** `/create_handoff` into `docs/handoffs/` when a session ends mid-phase, and `/resume_handoff` to pick it up.

### 25.4 Design loop

This covers the briefing render and bot replies (Phase 6), the showcase (Phases 11 and 12) and the dashboard (Phase 13).

1. **Shape.** `/impeccable init` once. Then run `/impeccable shape` for each surface before writing code: the Telegram briefing layout, bot replies, each website section.
2. **Build.** Use `/impeccable craft` with `emil-design-eng` guiding the details. Run `pick-ui-library` before adding any UI dependency.
3. **Motion** (Phase 12, against Section 20.1):
   - `find-animation-opportunities` confirms where motion earns its place and names what stays still.
   - `animation-vocabulary` describes each piece precisely before it is built.
   - `animate` and `/impeccable animate` build the UI motion. `/impeccable overdrive` builds the signal-field shader.
   - Before shipping, run `review-animations`, `improve-animations` and `animation-performance`, and test with reduced motion and with the Pause toggle.
4. **Harden.**
   - `break-ui` with worst-case data: 40 positions, 12-character tickers, a MYR 1,234,567,890.12 total, every source degraded, an empty portfolio, zero setups.
   - `/impeccable harden` for errors and overflow.
   - `mobile-native` for phone viewports, because the owner reads Telegram on a phone and most site visits will be mobile too.
5. **Gate.** `/impeccable audit` (accessibility, performance, responsive) and `/impeccable critique` pass, then `/impeccable polish`. Record the findings and fixes in the phase plan.
6. **Copy.** `/impeccable clarify` and `unslop` on all UI and briefing text.

---

## 26. Working agreement

- Act when the request is clear. Ask only when two readings lead to materially different work. For the open decisions below, propose an ADR with a recommendation and wait for the owner's choice.
- **Ask first, every time, before** you delete or overwrite files, make any paid API call, send a real Telegram message, touch the production database, run a backfill against production, change GitHub or Vercel settings or secrets, commit or push. One approval covers one action.
- Write tests first for domain maths and state machines. When a bug appears, reproduce it in a failing test, then fix its root cause.
- Report verification verbatim: the command and its output. When a check could not run (no Docker, no network), say so plainly and name what remains unverified.
- When an approach fails twice, stop and re-plan instead of patching on top of it.
- Match each file's existing style. Add comments only where the code cannot speak for itself.
- Secrets stay out of the repo, logs, fixtures and command lines.
- Stay within free tiers. Anything that would start billing needs the owner's approval first, with the cost stated.

**Open decisions to settle as ADRs in Phases 0–3:**

1. Crypto session timing versus the 08:00 deadline (Section 17.3).
2. Database host (Supabase or Neon) and backup storage (Actions artifacts, or Actions artifacts plus R2/B2).
3. US cross-check provider and its terms.
4. FX source and fallback.
5. Backtest entry assumption (next open or signal close) and the default exit model.
6. Whether narrative runs on schedule once enabled.
7. Benchmarks for relative strength (Bursa in particular).

---

## 27. First response

Before writing code, reply with:

1. The install plan for the Section 25 skills in your harness, including which parts cannot work there (see 25.1).
2. A one-page `ARCHITECTURE.md` draft: components, data flow, the typed contracts between stages, and where each job runs (GitHub Actions, Vercel, managed Postgres).
3. ADR stubs for the open decisions, each with your recommendation.
4. Only those questions where two readings lead to materially different work.

Then start Phase 0.
