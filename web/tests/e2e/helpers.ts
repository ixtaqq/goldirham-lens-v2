import type { Browser, BrowserContextOptions, Page } from "@playwright/test";

export const SECTIONS = ["top", "briefing", "pipeline", "method", "provenance", "scorecard", "reliability", "faq"];

export type Mode = "default" | "reduced" | "nojs";

export const MODES: Record<Mode, BrowserContextOptions> = {
  default: {},
  reduced: { reducedMotion: "reduce" },
  nojs: { javaScriptEnabled: false },
};

export async function openIn(browser: Browser, mode: Mode, options: BrowserContextOptions = {}) {
  const context = await browser.newContext({ ...MODES[mode], ...options });
  const page = await context.newPage();
  await page.goto("/");
  await settle(page, mode);
  return { context, page };
}

/** Scroll the page once so every reveal has fired, then return to the top. */
export async function settle(page: Page, mode: Mode) {
  await page.waitForLoadState("load");
  if (mode === "nojs") return;
  await page.evaluate(async () => {
    const step = window.innerHeight / 2;
    for (let y = 0; y < document.documentElement.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise((resolve) => setTimeout(resolve, 30));
    }
    window.scrollTo(0, 0);
  });
  await page.waitForTimeout(700);
  // Wait for finite animations only; the ticker loops forever by design.
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => Number.isFinite(Number(a.effect?.getComputedTiming().endTime)))
        .map((a) => a.finished.catch(() => null)),
    ),
  );
}

/** What a reader or screen reader gets: visible text, without decorative aria-hidden layers. */
export async function mainText(page: Page) {
  return page.evaluate(() => {
    const style = document.createElement("style");
    style.textContent = '[aria-hidden="true"] { display: none !important; }';
    document.head.append(style);
    const text = (document.querySelector("main") as HTMLElement).innerText.replace(/\s+/g, " ").trim();
    style.remove();
    return text;
  });
}

/** Counts requestAnimationFrame calls, installed before any page script runs. */
export const COUNT_FRAMES = () => {
  const original = window.requestAnimationFrame.bind(window);
  (window as unknown as { __frames: number }).__frames = 0;
  window.requestAnimationFrame = (callback) => {
    (window as unknown as { __frames: number }).__frames += 1;
    return original(callback);
  };
};
