import { cpus } from "node:os";

import { expect, test, type Page } from "@playwright/test";

// Probe: collects paused and live frame rates on CI runners to choose the budget check (ADR 0013).

type Window = { fps: number; longTasks: number[]; frames: string[] };

async function measure(page: Page, scroll: boolean, ms: number): Promise<Window> {
  return page.evaluate(
    ({ scroll, ms }) =>
      new Promise<Window>((resolve) => {
        const start = performance.now();
        const at = (t: number) => Math.round(t - start);
        const longTasks: number[] = [];
        const frames: string[] = [];
        const tasks = new PerformanceObserver((list) => {
          for (const e of list.getEntries()) if (e.startTime >= start) longTasks.push(Math.round(e.duration));
        });
        tasks.observe({ type: "longtask", buffered: false });
        type Script = { invoker: string; sourceURL: string; sourceFunctionName: string; duration: number };
        type Frame = PerformanceEntry & { renderStart: number; scripts: Script[] };
        const loaf = new PerformanceObserver((list) => {
          for (const e of list.getEntries() as Frame[]) {
            if (e.duration <= 50 || e.startTime < start) continue;
            const scripts = e.scripts
              .map((s) => `${s.sourceURL.split("/").pop() || "(inline)"} ${Math.round(s.duration)}ms`)
              .join(", ");
            const render = e.renderStart ? Math.round(e.startTime + e.duration - e.renderStart) : 0;
            frames.push(`${Math.round(e.duration)}@${at(e.startTime)} r${render} [${scripts}]`);
          }
        });
        loaf.observe({ type: "long-animation-frame", buffered: false });
        const stamps: number[] = [];
        const tick = (now: number) => {
          stamps.push(now);
          if (scroll) window.scrollBy(0, 6);
          if (now - start < ms) requestAnimationFrame(tick);
          else {
            tasks.disconnect();
            loaf.disconnect();
            resolve({ fps: (stamps.length - 1) / ((now - start) / 1000), longTasks, frames });
          }
        };
        requestAnimationFrame(tick);
      }),
    { scroll, ms },
  );
}

const benchmark = (page: Page) =>
  page.evaluate(() => {
    const end = performance.now() + 300;
    let n = 0;
    while (performance.now() < end) {
      const a: string[] = [];
      for (let i = 0; i < 200; i += 1) a.push(String(i * 7));
      a.sort();
      n += 1;
    }
    return n;
  });

async function setPaused(page: Page, paused: boolean) {
  const toggle = page.getByRole("button", { name: "Pause motion" });
  if ((await toggle.getAttribute("aria-pressed")) !== String(paused)) await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", String(paused));
}

const fmt = (w: Window) => `${w.fps.toFixed(1)} lt ${w.longTasks.length}/${w.longTasks.reduce((a, b) => a + b, 0)}ms`;

test("probe @chromium-only", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "needs the DevTools protocol");
  test.setTimeout(240_000);
  await page.goto("/");
  await expect(page.locator(".signal-field")).toHaveClass(/field-live/);
  const cdp = await page.context().newCDPSession(page);
  const rows: string[] = [`PROBE cpu ${cpus()[0]?.model} x${cpus().length}`];
  rows.push(
    `PROBE gl ${await page.evaluate(() => {
      const gl = document.createElement("canvas").getContext("webgl2");
      const info = gl?.getExtension("WEBGL_debug_renderer_info");
      return info ? gl?.getParameter(info.UNMASKED_RENDERER_WEBGL) : "unknown";
    })}`,
  );
  const since = await page.evaluate(() => performance.now());
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await page.waitForTimeout(1000);
  const first = await measure(page, true, 3000);
  rows.push(`PROBE first live scroll ${fmt(first)} (window began ${Math.round(since)}ms after load + 1s)`);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
  rows.push(`PROBE bench x1 ${await benchmark(page)}`);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  rows.push(`PROBE bench x4 ${await benchmark(page)}`);
  const details: string[] = [`PROBE first LoAF ${first.frames.join("; ")}`];
  for (let round = 0; round < 4; round += 1) {
    for (const paused of round % 2 ? [true, false] : [false, true]) {
      await setPaused(page, paused);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(1000);
      const t = Math.round(await page.evaluate(() => performance.now()));
      const still = await measure(page, false, 2000);
      const scroll = await measure(page, true, 3000);
      const name = paused ? "paused" : "live  ";
      rows.push(`PROBE r${round} t${t} ${name} still ${fmt(still)} | scroll ${fmt(scroll)}`);
      details.push(`PROBE r${round} ${name} still LoAF ${still.frames.join("; ")}`);
      details.push(`PROBE r${round} ${name} scroll LoAF ${scroll.frames.join("; ")}`);
    }
  }
  rows.push(`PROBE bench x4 after ${await benchmark(page)}`);
  console.log([...rows, ...details].join("\n"));
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
