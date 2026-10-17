import { expect, test } from "@playwright/test";

// Chromium only: CPU throttling and long-task timing come from the DevTools protocol.
test("motion holds its frame budget under 4x CPU throttling @chromium-only", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "needs the DevTools protocol");
  await page.goto("/");
  await expect(page.locator(".signal-field")).toHaveClass(/field-live/);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });

  const result = await page.evaluate(
    () =>
      new Promise<{ fps: number; longTasks: string[]; frames: string[] }>((resolve) => {
        const start = performance.now();
        const at = (t: number) => Math.round(t - start);
        const longTasks: string[] = [];
        const frames: string[] = [];
        const tasks = new PerformanceObserver((list) => {
          for (const e of list.getEntries()) longTasks.push(`${Math.round(e.duration)}ms at ${at(e.startTime)}ms`);
        });
        tasks.observe({ type: "longtask", buffered: false });
        // Long Animation Frames name the scripts behind a slow frame, so a failure says what caused it.
        type Script = { invoker: string; sourceURL: string; sourceFunctionName: string; duration: number };
        type Frame = PerformanceEntry & { styleAndLayoutStart: number; renderStart: number; scripts: Script[] };
        const loaf = new PerformanceObserver((list) => {
          for (const e of list.getEntries() as Frame[]) {
            if (e.duration <= 50) continue;
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
  test.info().annotations.push({ type: "fps (4x throttle)", description: result.fps.toFixed(1) });
  test.info().annotations.push({ type: "long tasks", description: result.longTasks.join("; ") || "none" });
  test.info().annotations.push({ type: "long animation frames", description: result.frames.join("; ") || "none" });
  const why = `long tasks: ${result.longTasks.join("; ")} | long animation frames: ${result.frames.join("; ")}`;
  expect(result.fps, why).toBeGreaterThanOrEqual(45);
  expect(result.longTasks, why).toEqual([]);
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
