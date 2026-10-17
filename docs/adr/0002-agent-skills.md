# 0002. Agent skills and their pinned sources

Status: accepted, 2026-10-16.

## Context

The owner requires four third-party skill sets for building this project. Skills are instructions an agent follows, so an unpinned source could change what the agent does without review.

## Decision

Each source is pinned to a commit and was read before use.

| Source | Commit | Installed as | Used for |
| --- | --- | --- | --- |
| `cursor/plugins` pstack | `23e4138daa01c42d4969f7a5465f82704e64f798` | Junctions in `.claude/skills/`, one per skill | `tdd`, `architect`, `unslop`, `technical-writing`, `no-comments`, `blast-radius`, the principle skills |
| `pbakaus/impeccable` | `e103efe779e2dd01274dabae83531fef00bf2563` | Junction `.claude/skills/impeccable` | `PRODUCT.md`, `DESIGN.md`, and the shape, craft, audit, critique and polish passes on the showcase |
| `emilkowalski/skills` | `e8a175de22ae1e49370fc144c1f3bb9aeedf988d` | Junctions for `animation-vocabulary`, `find-animation-opportunities`, `improve-animations`, `apple-design` | Motion design on the showcase |
| `emilkowalski/skills` `animation-performance` | `2d228630ba1446365f614a108cb8252f1feda202` | Copied into `.claude/vendor/emil-animation-performance/` | Motion performance review; the vendored clone predates this skill |
| `humanlayer/humanlayer` `.claude/commands`, `.claude/agents` | `99abe673498cf8bdcd5f989aebe9406a27185b3b` | Copied into `.claude/commands/` and `.claude/agents/` | Research, plan, implement, validate and handoff commands |

The owner's global agent setup already provides `emil-design-eng`, `animate`, `review-animations`, `break-ui`, `mobile-native` and `pick-ui-library` from the same Emil source.

`scripts/link-agent-skills.ps1` recreates the junctions from the owner's vendored clones in `E:\Workspace\agent-homebase\vendor`. Junctions are machine-local, so `.claude/skills/` is git-ignored.

## Adaptations

- pstack is written for Cursor. Its model routing, `poteto-agent` subagent and `cursor-team-kit` skills do not exist in Claude Code. `unslop` with `no-comments` stands in for `deslop`, and the built-in browser or Playwright stands in for `control-ui`.
- HumanLayer's commands referred to `thoughts/shared/`, Linear and `humanlayer thoughts sync`. The copies here write to `docs/research/`, `docs/plans/` and `docs/handoffs/`, and skip the sync and Linear steps. Only the `_nt` variants of the research and planning commands are installed.
- Impeccable reads `PRODUCT.md` and `DESIGN.md` at the repository root. Both were seeded from the build prompt's product and brand sections.

## Consequences

- The owner's working agreement in `AGENTS.md` overrides any skill. No skill can approve a commit, push, deploy, real Telegram send, paid API call or production change.
- Updating a skill means reading the diff between the pinned commit and the new one, then updating this table.
