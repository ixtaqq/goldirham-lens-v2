# 0013. Frame budget measured as the median of several windows

Status: accepted, 2026-10-18.

## Context

The build prompt (Section 20.1) sets the motion budget at 45 fps or more, with no long tasks caused by animation, under 4x CPU throttling. `web/tests/e2e/performance.spec.ts` checked it on one 3-second scrolling window that began a second after throttling switched on.

CI run 39038654348 failed that check at 28.9 fps and again at 29.9 fps on its retry. Its long animation frames lasted 50 to 88 ms and named no script, so the time went to rendering. The pull request run of the same commit passed, and so did a rerun of the failed job. On the owner's i7-14700K the same test holds 60 fps at 4x and 8x throttling. This repository's runners have 2 vCPUs, and WebGL runs in software (SwiftShader) there and in local Playwright runs.

A probe in commits 3619ece and 05f1e20 measured five CI runs on three runner CPUs (AMD EPYC 9V74, 9V45 and 7763). Each run measured four rounds of one window with motion paused and one with motion live, alternating which came first.

- Slow windows came only in the first 15 seconds or so after the browser started, and they slowed the paused page too. On the EPYC 7763 runner the first paused window ran at 31.4 fps and the first live one at 42.4 fps.
- Every later window ran at 56 to 60 fps with no long tasks, paused or live, on every runner.
- The original test's single window fell inside that early stretch, and its retry started a fresh browser and fell inside it again.

## Options

- **Several windows, median.** Keeps the brief's numbers and keeps the check blocking. One slow window can no longer decide the result.
- **Added cost against a paused baseline.** Cancels a slow runner, but the bar becomes a ratio. Paused windows ran at 56 to 60 fps on CI, so the 45/60 ratio would allow about 42 fps, below the brief.
- **Absolute check in a scheduled or dispatched job, relative check blocking.** Takes the brief's numbers out of the merge gate, though every runner sampled met them once warmed up.

## Decision

Measure several windows and assert on the median. From the second option, keep the paused windows as a control, not as the bar.

- Five rounds, each with one paused and one live window of the same 3-second scroll, alternating which goes first. Each window starts after a 1-second settle.
- The median live window must hold 45 fps or more and have no long tasks. These are the brief's numbers.
- The log line and any failure message list every window, the paused median and the runner's CPU. If the paused windows are slow as well, the runner is slow, not the motion.

## Consequences

- The test takes about 45 seconds instead of about 5.
- A regression that pushes most windows over budget fails. One that touches fewer than half of them can pass once and fail the next time. The log shows every window, so a near miss is visible.
- A runner that stays slow for the whole test still fails, and the paused median in the message says so. If that recurs, revisit the other two options.
- The test still measures a scroll, and the field holds its frame while the page scrolls, so it does not measure the field drawing. In the probe's still windows on CI, the first live window dropped to 31 to 36 fps on all three EPYC 9V74 runners. Four of 20 live still windows had a 52 to 126 ms long task, while all 20 paused still windows held 60 fps with none. That needs its own check.
