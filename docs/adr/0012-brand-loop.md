# 0012. Rendered brand loop and social card with Remotion

Status: accepted, 2026-10-17.

## Context

The build prompt's motion system lists an optional brand loop: a 10 to 15 second render of the signal field and hero sequence for the README, social cards and the hero poster. A WebGL loop driven by `requestAnimationFrame` cannot be rendered frame by frame, so the video needs a deterministic, frame-driven version of the same scene.

## Decision

- A separate `video/` package uses Remotion 4.0.532. The site's dependencies and CI are unchanged.
- One `Scene` component draws a given frame as SVG and HTML. It reuses the demo fixture's traces, `layoutFor()` and `verifyPulse()` from `web/lib/field.ts`, `tracePath()` from `web/lib/geometry.ts`, and the mark's geometry from `web/lib/mark.ts`. The site's `<Mark>` now reads the same geometry.
- The loop is 15 seconds at 30fps and closes without a seam. Each trace drifts exactly one tile, both verification moments fall inside the loop, and the outro fades back to the opening state.
- `npm run render` writes `docs/media/brand-loop.mp4`, `docs/media/brand-loop.webm` and `web/public/og.png`. The site uses the last as its Open Graph and Twitter image.

## Consequences

- The video shows the same traces, pulse timing and mark as the live page, from the same data.
- The traces drift faster in the video (about 150 to 220 px/s at 1080p) than on the site (30 to 60 second cycles), because a seamless 15-second loop needs whole-tile movement.
- Renders are committed artifacts. Re-render after changing the demo export, the field layout or the mark.
- Remotion's license is free for individuals and companies of up to three people; larger companies need a company license. This project is owned by one person. Check the license again before anyone else uses the package.
