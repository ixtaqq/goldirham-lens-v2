# Goldirham Lens v2

![Numbers before narrative. Demo data, synthetic market.](web/public/og.png)

**Numbers before narrative.** A private research service for one long-horizon investor in
Malaysia. Every morning it collects public market data for crypto, US stocks and ETFs, and
Bursa Malaysia stocks, verifies it, computes indicators, setups, holding reviews and portfolio
state in Python, and sends one concise briefing to a private Telegram chat before 08:00
Asia/Kuala_Lumpur.

It is research and decision support. It never places trades, never connects to a broker, and
never gives personalised financial advice.

## How it runs

There is no server to maintain.

| Job | Runs on |
| --- | --- |
| Daily briefing | GitHub Actions `daily.yml`, scheduled 07:00 and 07:40 MYT |
| Telegram commands | Vercel Python function (`api/telegram.py`) |
| Data | Managed PostgreSQL (Supabase free tier by default) |
| Missed-run alert | Healthchecks.io dead-man's switch |
| Showcase website | Vercel (`web/`) |
| Private dashboard (optional) | A second Vercel project (`api/dashboard.py`) |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the components and contracts, and
[docs/RUNBOOK.md](docs/RUNBOOK.md) for setup and operations.

## Develop

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), Node 22+ and Docker Desktop.

```powershell
python -m uv sync --all-extras
python -m uv run poe db-up
$env:TEST_DATABASE_URL = "postgresql+asyncpg://lens:lens-local-only@127.0.0.1:55432/lens_test"
python -m uv run poe check
```

Install the pre-commit hooks once (ruff and gitleaks) with `python -m uv run --with pre-commit pre-commit install`.

`poe check` runs exactly what CI runs: format, lint, strict types, import contracts, the
webhook requirements check, and the full test suite including PostgreSQL integration tests.

Preview a briefing without writing anything or sending anything:

```powershell
python -m uv run lens cycle run --dry-run
```

## Showcase website

Live at **https://goldirham-lens.vercel.app** (Vercel project `goldirham-lens`, root `web`, production branch `main`).

`web/` is a static Next.js site that explains the method with a sample briefing. Its data comes
from `lens demo export`, which runs the real validation, analysis and rendering code over a seeded
synthetic market and writes `web/data/demo.json`. CI fails if that file is out of date.

```powershell
python -m uv run lens demo export
cd web
npm ci
npm run build
npm run test:e2e
```

The motion layer (signal field, hero sequence, pinned pipeline, day switcher) can be switched off
at build time with `NEXT_PUBLIC_MOTION=off`; the page is complete without it.

The brand loop ([MP4](docs/media/brand-loop.mp4), [WebM](docs/media/brand-loop.webm)) and the
social card are rendered from the same demo data with Remotion:

```powershell
cd video
npm ci
npm run render
```

## Documentation

| Document | Contents |
| --- | --- |
| [docs/build-prompt.md](docs/build-prompt.md) | The full build specification this repository implements |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, data flow, typed contracts |
| [docs/STRATEGY.md](docs/STRATEGY.md) | Rules, reason codes and metric definitions |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | First-time setup, daily operations, recovery |
| [docs/SECURITY.md](docs/SECURITY.md) | Access, secrets, database roles, data that leaves the service |
| [docs/adr/](docs/adr/) | Architecture decisions |
| [AGENTS.md](AGENTS.md) | Conventions and the working agreement for coding agents |
| [PRODUCT.md](PRODUCT.md), [DESIGN.md](DESIGN.md) | Product facts and the visual system for the showcase |
| [CHANGELOG.md](CHANGELOG.md) | Dated changes and verification evidence |
