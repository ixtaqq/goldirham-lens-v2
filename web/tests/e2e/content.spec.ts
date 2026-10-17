import { expect, test } from "@playwright/test";

import { mainText, openIn, SECTIONS, type Mode } from "./helpers";

const modes: Mode[] = ["default", "reduced", "nojs"];

test("content and reading order are identical with motion, reduced motion and no JavaScript", async ({ browser }) => {
  const texts: Record<string, string> = {};
  for (const mode of modes) {
    const { context, page } = await openIn(browser, mode);
    texts[mode] = await mainText(page);
    await context.close();
  }
  expect(texts.default).toContain("Numbers before narrative.");
  expect(texts.default).toContain("No new setups today.");
  expect(texts.reduced).toBe(texts.default);
  expect(texts.nojs).toBe(texts.default);
});

for (const mode of modes) {
  test(`every section renders and is captured (${mode})`, async ({ browser }, info) => {
    // Eight full-section captures; WebKit on a shared CI runner needs more than the default 30s.
    test.setTimeout(90_000);
    const { context, page } = await openIn(browser, mode);
    for (const id of SECTIONS) {
      const section = page.locator(`#${id}`);
      await section.scrollIntoViewIfNeeded();
      await expect(section).toBeVisible();
      await info.attach(`${mode}-${id}.png`, { body: await section.screenshot(), contentType: "image/png" });
    }
    await context.close();
  });
}

test("every figure on the page is labelled as demo data", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("DEMO DATA").first()).toBeVisible();
  await expect(page.locator("footer")).toContainText("synthetic");
});

test("nothing scrolls sideways at 360px", async ({ browser }) => {
  for (const mode of modes) {
    const { context, page } = await openIn(browser, mode, { viewport: { width: 360, height: 760 } });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, mode).toBeLessThanOrEqual(0);
    await context.close();
  }
});

test("without JavaScript the day tabs still switch the briefing", async ({ browser }) => {
  const { context, page } = await openIn(browser, "nojs");
  const panel = page.locator("#day-panel");
  await expect(panel).toContainText("No new setups today.");
  await page.locator('[role="tab"][data-day="setup"]').click();
  await expect(page).toHaveURL(/#day-setup$/);
  await expect(page.locator("#day-setup")).toBeVisible();
  await expect(page.locator("#day-setup")).toContainText("New setup: KSTL");
  await expect(page.locator(".day-live [data-day-content]").first()).toBeHidden();
  await context.close();
});

test("the day switcher changes only what changed and keeps the URL shareable", async ({ page }) => {
  await page.goto("/");
  const tab = page.getByRole("tab", { name: /Setup day/ });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL(/#day-setup$/);
  const panel = page.getByRole("tabpanel");
  await expect(panel).toContainText("New setup: KSTL");
  await expect(panel).toContainText("FERN-USD: price sources disagree on a recent close");
  await page.reload();
  await expect(page.getByRole("tab", { name: /Setup day/ })).toHaveAttribute("aria-selected", "true");
});

test("day tabs work from the keyboard with visible focus", async ({ page }) => {
  await page.goto("/");
  const quiet = page.getByRole("tab", { name: /Quiet day/ });
  await quiet.focus();
  await page.keyboard.press("ArrowRight");
  const setup = page.getByRole("tab", { name: /Setup day/ });
  await expect(setup).toBeFocused();
  await expect(setup).toHaveAttribute("aria-selected", "true");
  const outline = await setup.evaluate((el) => getComputedStyle(el).outlineStyle);
  expect(outline).not.toBe("none");
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: /Degraded data/ })).toBeFocused();
});
