# Showcase and motion layer implementation plan

## Overview

Build the public showcase in `web/` (Phase 11) and its motion layer (Phase 12) from the build prompt's Sections 20 and 20.1. The page explains the method with a sample briefing produced by the real pipeline over synthetic data, and never connects to the service.

## Current state analysis

- The Python pipeline renders Telegram HTML from a `BriefingDocument` (`src/lens/delivery/renderer.py`) and chunks it (`delivery/chunker.py`).
- `lens demo export` did not exist. `ci.yml` checked `web/data/demo.json` with `git diff` but never regenerated it.
- No `web/` code, no `PRODUCT.md` or `DESIGN.md`.

## Desired end state

- `lens demo export` writes a deterministic `web/data/demo.json` from a seeded synthetic market, and `--check` fails CI when it is stale.
- A static Next.js export that renders all content without JavaScript, with a motion layer that can be paused, honours reduced motion, and can be switched off at build time.

### Key discoveries

- `analysis.analyze()` and `compose.compose()` are pure functions of `CycleInputs`, so the demo can run them without a database (`src/lens/pipeline/analysis.py:164`).
- Integer basis-point random steps keep the synthetic market identical on every platform; float `exp` would not.
- `bootstrap_interval` could print `-0.00` for a bound that rounds to zero (`src/lens/domain/scorecard.py:72`); fixed with a test.
- The narrative service ran with unverified token rates; it now refuses (`src/lens/narrative/service.py`), with a test.

## What we're not doing

- The optional Remotion brand loop. Nothing in the page needs a rendered video.
- The private dashboard (Phase 13).
- Deploying to Vercel. That is the owner's step in the runbook.

## Implementation approach

Static first, motion as a layer gated by `.motion-ready` (added after hydration), `hero-play` (added before paint, CSS only) and `NEXT_PUBLIC_MOTION`.

## Phase 1: Demo export

### Changes required

- `src/lens/demo.py`: synthetic market, real `assess()` and `assess_readiness()`, three days through `analyze()`, `compose()`, `render_sections()` and `chunk()`, the setup-day pipeline story, a demo backtest through `build_report()`, field traces, ticker rows, and the rule tables parsed from `docs/STRATEGY.md`.
- `src/lens/cli.py`: `lens demo export [--check]`.
- `tests/test_demo.py`; `ci.yml` runs `lens demo export --check`.

### Success criteria

#### Automated verification

- [x] `python -m uv run pytest tests/test_demo.py --no-db` passes (6 tests)
- [x] `python -m uv run lens demo export --check` prints that the file is up to date
- [x] `python -m uv run poe check` passes

## Phase 2: Static showcase (Phase 11)

### Changes required

- `web/app`, `web/components`, `web/lib`: hero, briefing with day switcher (CSS `:target` without JavaScript), pipeline steps, method, provenance, scorecard and backtest, reliability practices, FAQ, footer.
- One `@theme` token file in `web/app/globals.css`.
- Unit tests (Vitest) and Playwright with axe.

### Success criteria

#### Automated verification

- [x] `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` pass
- [x] With `NEXT_PUBLIC_MOTION=off`: content and accessibility specs pass in Chromium, mobile Chromium and WebKit (27 tests)
- [x] `npm audit --omit=dev --audit-level=moderate` finds nothing

#### Manual verification

- [ ] The owner reads the page on a phone and confirms every claim is literal

## Phase 3: Motion layer (Phase 12)

### Changes required

- `SignalField.tsx`: WebGL2 traces with the pointer lens and verification moment, Canvas 2D fallback, SVG poster, DPR caps, half-resolution fallback, stop on hidden tab, pause or reduced motion.
- Hero proof sequence (CSS), briefing assembly, day switcher (Motion `AnimatePresence` and `layout`), pinned pipeline (sticky plus a scroll handler), chart draw-ins, ticker, micro-interactions, Pause motion toggle stored in `localStorage`.

### Success criteria

#### Automated verification

- [x] `npm run test:e2e` passes (46 tests): three-mode content parity, axe, Pause stops animation frames and survives reload, Canvas and poster fallbacks, keyboard tabs, no sideways scroll at 360px, CLS under 0.01, 4x-throttled fps of 45 or more with no long tasks
- [x] Lighthouse 13.5 through its Node API against the gzip-serving export: mobile performance 98, accessibility 100, best practices 100; desktop 100, 100, 100
- [x] Client JavaScript holding Motion, the field and all client components is 47.8 KB gzipped (budget 60 KB); the field renderer's source is at most 4.6 KB gzipped (budget 25 KB)

#### Manual verification

- [ ] Frame rate on a real mid-range phone (only desktop CPU throttling was measured)
- [ ] The motion feels calm at full speed and at 0.25x in the DevTools Animations panel

## Testing strategy

- Python: determinism, the three-day story, message size, labels, CLI `--check`.
- Web unit: Telegram HTML parser, section grouping, geometry, boot script, storage guards, demo data shape.
- Web end-to-end: as listed above.

## Skill passes and findings

- impeccable: PRODUCT.md from the brief (no interview), surface brief with direction contract, detector (no findings), in-thread finish review (disposition fix, then ship after six resolved items), documenter (DESIGN.md and `.impeccable/design.json`).
- review-animations and animation-performance: removed the repeated section reveal, stagger to 60ms, no `scale(0)` on the FAQ icon, reduced-motion variants for the menu sheet and FAQ icon.
- pick-ui-library: Motion for enter, exit and layout; charts left the curated list (recharts) for build-time SVG, so they render without JavaScript and stay inside the budget.

## References

- `docs/build-prompt.md` Sections 20, 20.1, 24 and 25
- `.impeccable/surfaces/web-app-page-tsx.md`
