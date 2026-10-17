# Agent instructions

Conventions for any coding agent working in this repository. The owner's working agreement at the end overrides every skill and playbook.

## What this is

A private research service for one investor. A GitHub Actions job builds one Telegram briefing a day from public market data. A Vercel function answers bot commands. `web/` is a static showcase that runs on synthetic demo data. Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before changing anything that crosses a package boundary.

## Commands

Windows PowerShell 5.1 is the default shell. Chain with `;`, not `&&`.

| Task | Command |
| --- | --- |
| Install | `python -m uv sync --all-extras` |
| Start Postgres for tests | `python -m uv run poe db-up` (Docker Desktop must be running) |
| Everything CI runs | `$env:TEST_DATABASE_URL = "postgresql+asyncpg://lens:lens-local-only@127.0.0.1:55432/lens_test"; python -m uv run poe check` |
| Tests without Postgres | `python -m uv run poe test-fast` (lists the skipped database tests) |
| Preview a briefing, no writes, no send | `python -m uv run lens cycle run --dry-run` |
| Regenerate showcase data | `python -m uv run lens demo export` |
| Showcase checks | `cd web; npm ci; npm run lint; npm run typecheck; npm test; npm run build; npm run test:e2e` |

Tests only run against databases whose name starts with `lens_test`.

## Rules the code depends on

- **Python owns the facts.** Every number a reader sees is computed in Python and carries its source and session date. A model may write words, never numbers.
- **Completed sessions only.** Analysis reads bars whose exchange session has closed. Live quotes never feed a rule.
- **Fail closed.** Suspect, disputed, stale or missing data produces no setup and a stated reason code. An uncertain delivery is held, never resent automatically.
- **Pure core.** `domain/`, `pipeline/analysis.py` and `pipeline/compose.py` never touch the network or the database. `import-linter` enforces the domain contracts.
- **Money is `Decimal`.** Setup levels are rounded to the market's price increment before any rule checks them.
- **Strategies need evidence.** Never activate a strategy version for the owner. `lens strategy activate` is the owner's command.
- **Replayable.** Any change to analysis or rendering must keep `lens replay` byte-identical for stored inputs, or ship with updated golden files and a `CHANGELOG.md` entry that says why.

## Style

- Match the file you are in. Comments only where the code cannot say it.
- ruff with line length 100, strict mypy, no `Any` leaking out of adapters.
- Tests first for domain maths, state machines and every bug. Reproduce the bug in a failing test, then fix its cause.
- Owner-facing text (briefing copy, bot replies, website, docs) follows the `unslop` skill. No em dashes, no mid-sentence colons, sentence case headings.

## Skills

Pinned sources and adaptations are in [docs/adr/0002-agent-skills.md](docs/adr/0002-agent-skills.md). Run `scripts/link-agent-skills.ps1` once per machine to link them into `.claude/skills/`.

| Work | Skills |
| --- | --- |
| Planning a change | `/research_codebase_nt`, `/create_plan_nt` into `docs/plans/`, `/implement_plan`, `/validate_plan` |
| Domain and pipeline code | `architect`, `tdd`, `blast-radius`, `no-comments` |
| Docs and copy | `technical-writing`, `unslop` |
| Showcase | `impeccable` (reads `PRODUCT.md` and `DESIGN.md`), `emil-design-eng`, `pick-ui-library`, `break-ui`, `mobile-native` |
| Showcase motion | `find-animation-opportunities`, `animation-vocabulary`, `animate`, `review-animations`, `improve-animations`, `animation-performance` |
| Ending a session mid-task | `/create_handoff` into `docs/handoffs/` |

## Working agreement

Ask the owner first, every time, before you:

- delete or overwrite a file the owner did not ask you to change
- send a real Telegram message, including a non-dry-run `lens cycle run` or a workflow dispatch
- make a paid API call, including enabling the narrative
- touch the production database, run a production backfill, or run `migrate.yml`
- change GitHub or Vercel settings, secrets or webhooks
- commit or push

One approval covers one action. Secrets stay out of the repository, logs, fixtures and command lines. Stay within free tiers, and state the cost of anything that would start billing.
