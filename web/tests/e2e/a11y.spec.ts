import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { openIn, type Mode } from "./helpers";

// axe runs inside the page, so it needs JavaScript; the no-JS render is covered by content.spec.ts.
for (const mode of ["default", "reduced"] as Mode[]) {
  test(`no axe violations (${mode})`, async ({ browser }) => {
    const { context, page } = await openIn(browser, mode);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    const found = results.violations.map(
      (v) => `${v.id}: ${v.help} -> ${v.nodes.map((n) => n.target.join(" ")).slice(0, 4).join(" | ")}`,
    );
    expect(found).toEqual([]);
    await context.close();
  });
}

test("decorative motion layers are hidden from assistive technology", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".signal-field")).toHaveAttribute("aria-hidden", "true");
  for (const svg of await page.locator(".signal-field svg").all()) {
    await expect(svg).toHaveAttribute("aria-hidden", "true");
  }
});
