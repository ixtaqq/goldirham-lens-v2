import { cpus } from "node:os";

import { expect, test, type Page } from "@playwright/test";

type Window = { fps: number; longTasks: string[]; frames: string[] };

const ROUNDS = 5;

/** Scrolls 6px a frame for 3s and records only the work that starts inside that window. */
function measure(page: Page) {
  return page.evaluate(
    () =>
      new Promise<Window>((resolve) => {
        const start = performance.now();
        const at = (t: number) => Math.round(t - start);
        const longTasks: string[] = [];
        const frames: string[] = [];
        const tasks = new PerformanceObserver((list) => {
          for (const e of list.getEntries()) {
            if (e.startTime >= start) longTasks.push(`${Math.round(e.duration)}ms at ${at(e.startTime)}ms`);
          }
        });
        tasks.observe({ type: "longtask", buffered: false });
        // Long Animation Frames name the scripts behind a slow frame, so a failure says what caused it.
        type Script = { invoker: string; sourceURL: string; sourceFunctionName: string; duration: number };
        type Frame = PerformanceEntry & { styleAndLayoutStart: number; renderStart: number; scripts: Script[] };
        const loaf = new PerformanceObserver((list) => {
          for (const e of list.getEntries() as Frame[]) {
            if (e.duration <= 50 || e.startTime < start) continue;
            const scripts = e.scripts
              .map((s) => `${s.invoker} ${s.sourceURL.split("/").pop() || "(inline)"}:${s.sourceFunctionName} ${Math.round(s.duration)}ms`)
              .join(", ");
            const render = e.renderStart ? Math.round(e.startTime + e.duration - e.renderStart) : 0;
            frames.push(`${Math.round(e.duration)}ms at ${at(e.startTime)}ms, render ${render}ms, scripts [${scripts}]`);
          }
        });
        if (PerformanceObserver.supportedEntryTypes.includes("long-animation-frame")) {
          loaf.observe({ type: "long-animation-frame", buffered: false });
        }
        const stamps: number[] = [];
        const tick = (now: number) => {
          stamps.push(now);
          window.scrollBy(0, 6);
          if (now - start < 3000) requestAnimationFrame(tick);
          else {
            tasks.disconnect();
            loaf.disconnect();
            resolve({ fps: (stamps.length - 1) / ((now - start) / 1000), longTasks, frames });
          }
        };
        requestAnimationFrame(tick);
      }),
  );
}

async function setPaused(page: Page, paused: boolean) {
  const toggle = page.getByRole("button", { name: "Pause motion" });
  if ((await toggle.getAttribute("aria-pressed")) !== String(paused)) await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", String(paused));
}

const median = (values: number[]) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)] ?? 0;

const describe = (windows: Window[]) =>
  windows.map((w) => `${w.fps.toFixed(1)} fps${w.longTasks.length ? ` (long tasks ${w.longTasks.join(", ")})` : ""}`).join("; ");

// Chromium only: CPU throttling and long-task timing come from the DevTools protocol.
// ADR 0013: a 2-vCPU runner can stall for several seconds after the browser starts, with motion
// paused or live, so the budget applies to the median of five windows. The paused windows are the
// control that tells a slow runner from slow motion.
test("motion holds its frame budget under 4x CPU throttling @chromium-only", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "needs the DevTools protocol");
  test.setTimeout(120_000);
  await page.goto("/");
  await expect(page.locator(".signal-field")).toHaveClass(/field-live/);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });

  const live: Window[] = [];
  const paused: Window[] = [];
  for (let round = 0; round < ROUNDS; round += 1) {
    // Alternate which state goes first, so a runner that speeds up or slows down favours neither.
    for (const pause of round % 2 ? [true, false] : [false, true]) {
      await setPaused(page, pause);
      await page.evaluate(() => window.scrollTo(0, 0));
      // Settle first: the field resumes and the frame in flight when the state changed finishes.
      await page.waitForTimeout(1000);
      (pause ? paused : live).push(await measure(page));
    }
  }

  const fps = median(live.map((w) => w.fps));
  const longTasks = median(live.map((w) => w.longTasks.length));
  const runner = `${cpus()[0]?.model ?? "unknown CPU"} x${cpus().length}`;
  const report = `live median ${fps.toFixed(1)} fps [${describe(live)}] | paused median ${median(paused.map((w) => w.fps)).toFixed(1)} fps [${describe(paused)}] | ${runner}`;
  // CI keeps no report artifact, so the log is the record of how close each run came.
  console.log(`Frame budget under 4x throttling: ${report}`);
  test.info().annotations.push({ type: "fps (4x throttle, median of live windows)", description: fps.toFixed(1) });
  test.info().annotations.push({ type: "windows", description: report });
  const frames = live.flatMap((w, i) => w.frames.map((f) => `live ${i + 1}: ${f}`));
  test.info().annotations.push({ type: "long animation frames", description: frames.join("; ") || "none" });
  const why = `${report} | long animation frames: ${frames.join("; ") || "none"}`;
  expect(fps, why).toBeGreaterThanOrEqual(45);
  expect(longTasks, why).toBe(0);
});

test("layout never shifts while motion runs", async ({ page }) => {
  await page.goto("/");
  const cls = await page.evaluate(
    () =>
      new Promise<number>((resolve) => {
        let total = 0;
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries() as (PerformanceEntry & { value: number; hadRecentInput: boolean })[]) {
            if (!entry.hadRecentInput) total += entry.value;
          }
        }).observe({ type: "layout-shift", buffered: true });
        setTimeout(() => resolve(total), 2500);
      }),
  );
  expect(cls).toBeLessThan(0.01);
});
