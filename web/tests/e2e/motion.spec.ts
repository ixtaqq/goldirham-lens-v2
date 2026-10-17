import { expect, test } from "@playwright/test";

import { COUNT_FRAMES } from "./helpers";

const frames = (page: import("@playwright/test").Page) =>
  page.evaluate(() => (window as unknown as { __frames: number }).__frames);

test("the live field starts after first paint and the hero plays once per visit", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveClass(/motion-ready/);
  await expect(page.locator(".signal-field")).toHaveAttribute("data-field", /webgl|canvas/);
  await expect(page.locator(".signal-field")).toHaveClass(/field-live/);
  await expect(page.locator("html")).toHaveClass(/hero-play/);
  await page.reload();
  await expect(page.locator("html")).not.toHaveClass(/hero-play/);
});

test("Pause motion stops every animation frame and survives a reload", async ({ page }) => {
  await page.addInitScript(COUNT_FRAMES);
  await page.goto("/");
  await expect(page.locator(".signal-field")).toHaveClass(/field-live/);
  const toggle = page.getByRole("button", { name: "Pause motion" });
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await page.waitForTimeout(300);
  const before = await frames(page);
  await page.waitForTimeout(1500);
  expect((await frames(page)) - before).toBeLessThanOrEqual(1);
  const ticker = await page.locator(".ticker-track").evaluate((el) => getComputedStyle(el).animationPlayState);
  expect(ticker).toBe("paused");

  await page.reload();
  await expect(page.locator("html")).toHaveClass(/motion-paused/);
  await expect(page.getByRole("button", { name: "Pause motion" })).toHaveAttribute("aria-pressed", "true");
  await page.waitForTimeout(800);
  const afterReload = await frames(page);
  await page.waitForTimeout(1000);
  expect((await frames(page)) - afterReload).toBeLessThanOrEqual(1);
});

test("reduced motion shows the poster and every final state", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();
  await page.goto("/");
  await page.waitForTimeout(800);
  await expect(page.locator(".signal-field")).toHaveAttribute("data-field", "poster");
  await expect(page.locator("html")).not.toHaveClass(/motion-ready|hero-play/);
  await expect(page.locator(".field-poster svg")).toBeVisible();
  const opacity = await page.locator('#pipeline [data-step="1"] .step-row').first().evaluate((el) => getComputedStyle(el).opacity);
  expect(opacity).toBe("1");
  await context.close();
});

test("without WebGL the Canvas 2D fallback renders @chromium-only", async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...rest: unknown[]) {
      if (type === "webgl2" || type === "webgl") return null;
      return (original as (...args: unknown[]) => unknown).call(this, type, ...rest);
    } as typeof original;
  });
  await page.goto("/");
  await expect(page.locator(".signal-field")).toHaveAttribute("data-field", "canvas");
  await expect(page.locator(".signal-field")).toHaveClass(/field-live/);
});

test("without WebGL or Canvas 2D the poster stays", async ({ page }) => {
  await page.addInitScript(() => {
    HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext;
  });
  await page.goto("/");
  await page.waitForTimeout(800);
  await expect(page.locator(".signal-field")).toHaveAttribute("data-field", "poster");
  await expect(page.locator(".field-poster svg")).toBeVisible();
});

test("the field never paints mint outside the verification moment", async ({ page }) => {
  await page.goto("/");
  const mint = await page.locator(".field-poster path").evaluateAll((paths) =>
    paths.filter((p) => getComputedStyle(p).stroke.includes("121, 213, 194")).length,
  );
  expect(mint).toBe(0);
});
