# Changelog

All dates are Asia/Kuala_Lumpur. Nothing here has been deployed or committed yet.

## Unreleased: v2.0 foundation (2026-10-16)

### Added

- **Daily cycle without a server.** GitHub Actions runs the cycle at 07:00 and 07:40 MYT behind a per-day claim. A Healthchecks dead-man's switch alerts if no success arrives by 08:15. A degraded briefing goes out when the database is down. See ADR 0001 and ADR 0007.
- **Data layer.** Yahoo, Coinbase, Binance and Alpha Vantage adapters with cross-checks, quality rules, readiness, BNM and ECB FX, and Bursa holiday overrides. See ADR 0004 and ADR 0010.
- **Domain core.** Indicators, two strategies with reason codes, tick-rounded setups, holding reviews, signal evaluation with two exit models, portfolio valuation in MYR, and the scorecard.
- **Backtest and activation gate.** A strategy version needs a stored report before `lens strategy activate` accepts it. The first report did not beat random entries, and no strategy is active. See ADR 0005.
- **Delivery and bot.** Telegram HTML renderer, chunker, a delivery state machine with held resends, and a Vercel webhook with an owner guard and one-tap confirmations.
- **Optional narrative.** Off by default. A placeholder-only verifier and an atomic daily budget. See ADR 0008.
- **Operations.** Encrypted backups, a weekly restore drill, an approval-gated migration workflow, a provider drift check, and `lens doctor`.
- **`lens demo export`.** The real validation, analysis and rendering code over a seeded synthetic market, written to `web/data/demo.json`. `--check` runs in CI.
- **Showcase (`web/`).** A static Next.js site with the sample briefing for three demo days, the pipeline story, rule tables read from `docs/STRATEGY.md`, provenance, the demo backtest, reliability practices and FAQ. Content renders without JavaScript.
- **Motion layer.** A WebGL2 signal field with a pointer lens and verification moment, a Canvas 2D fallback and an SVG poster. Also the hero proof sequence, briefing assembly, the day switcher, a pinned pipeline, chart draw-ins, the ticker and a Pause motion control. Reduced motion is honoured, and `NEXT_PUBLIC_MOTION=off` removes the whole layer.
- **Docs.** Architecture, strategy reference, runbook, security reference, ADRs 0001 to 0010, `AGENTS.md`, `PRODUCT.md`, `DESIGN.md`, and a plan for the showcase phases.

### Fixed during this build

- `bootstrap_interval` no longer prints `-0.00` for a bound that rounds to zero.
- The narrative refuses to run while `narrative.rates_verified_on` is unset, so it cannot spend money at unchecked prices.
- `ci.yml` checked the demo export with `git diff` without regenerating it. It now runs `lens demo export --check`.
- README pointed the test database at `lens`, which the test fixture refuses. It now points at `lens_test`.
- The content-parity end-to-end test ran out of time in WebKit on CI. Parity and section screenshots are now separate tests.
- Cron runs of the five scheduled workflows skip until the repository variable `SCHEDULES_ENABLED` is `true` (runbook step 10). Manual runs are unaffected.
- The signal field held only 32 to 34 fps under 4x throttling on the CI runner. Locally it took 20x throttling to reproduce (31.6 fps). It now redraws at about 30 fps unless the pointer moves the lens, holds its frame while the page scrolls, moves the parallax on the compositor, stops once the hero is out of view, and draws without MSAA. The same 20x case now measures 51.5 fps.

### Known limits

- ESLint stays on 9.39.5, which is out of upstream support. ESLint 10 crashes inside `eslint-plugin-react` as bundled by `eslint-config-next` 16.3.8.
- `npm audit` reports `braces` 3.0.3 and earlier through the ESLint plugin, with no patched release. CI gates shipped dependencies at moderate and dev tooling at critical.
- Frame rate was measured with 4x CPU throttling on a desktop, not on a phone.
- The optional Remotion brand loop was not built.

### Verification

Run locally on Windows 11, 2026-10-16 and 2026-10-17. In the first CI run, the Python and repository jobs passed and the web job failed on the WebKit timeout fixed above.

| Check | Command | Result |
| --- | --- | --- |
| Python gate (format, lint, strict mypy, import contracts, webhook requirements, tests, domain coverage) | `python -m uv run poe check` with Postgres 17 in Docker | Exit 0. 337 passed and 4 skipped (live network tests). Total coverage 90.56%, domain coverage 98%. 5 golden briefings match. |
| Demo export is current | `python -m uv run lens demo export --check` | `web\data\demo.json is up to date` |
| Workflows | `actionlint 1.7.12` | Exit 0 |
| Web lint and types | `npm run lint`, `npm run typecheck` | Exit 0 |
| Web unit tests | `npm test` | 22 passed |
| End-to-end tests | `npm run test:e2e` (Chromium, mobile Chromium, WebKit, then performance on its own) | 55 passed |
| Static page without motion | `NEXT_PUBLIC_MOTION=off` build, then the content and accessibility specs | 27 passed |
| Lighthouse 13.5, motion on, gzip-serving local export | Node API against Playwright Chromium | Mobile: performance 98, accessibility 100, best practices 100, LCP 2.4 s, CLS 0. Desktop: 100, 100, 100. |
| Frame budget | 4x CPU throttling in Chromium while scrolling | About 60 fps, no long tasks |
| JavaScript budget | gzip of the built chunks | 47.8 KB for Motion, the field and all client components (budget 60 KB). The field renderer's source is at most 4.6 KB (budget 25 KB). |
| Dependencies | `npm audit --omit=dev --audit-level=moderate` | 0 vulnerabilities |
| Live data | `lens readiness`, `lens cycle run --dry-run`, `lens backtest` | Crypto and Bursa ready. US stays single source until an Alpha Vantage key is set. The dry run renders in 8 s. The backtest report is in `reports/`. |
