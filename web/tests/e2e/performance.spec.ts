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
      new Promise<{ fps: number; longTasks: number; worst: number }>((resolve) => {
        const longTasks: number[] = [];
        const observer = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) longTasks.push(entry.duration);
        });
        observer.observe({ type: "longtask", buffered: false });
        const stamps: number[] = [];
        const start = performance.now();
        const tick = (now: number) => {
          stamps.push(now);
          window.scrollBy(0, 6);
          if (now - start < 3000) requestAnimationFrame(tick);
          else {
            observer.disconnect();
            const gaps = stamps.slice(1).map((t, i) => t - (stamps[i] ?? t));
            resolve({
              fps: (stamps.length - 1) / ((now - start) / 1000),
              longTasks: longTasks.length,
              worst: Math.max(0, ...gaps),
            });
          }
        };
        requestAnimationFrame(tick);
      }),
  );
  test.info().annotations.push({ type: "fps (4x throttle)", description: result.fps.toFixed(1) });
  test.info().annotations.push({ type: "long tasks", description: String(result.longTasks) });
  expect(result.fps).toBeGreaterThanOrEqual(45);
  expect(result.longTasks).toBe(0);
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
