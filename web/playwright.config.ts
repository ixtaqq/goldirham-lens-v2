import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: { baseURL: "http://127.0.0.1:4173", trace: "retain-on-failure" },
  webServer: {
    command: "node scripts/serve.mjs out 4173",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] }, testIgnore: /performance/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testIgnore: /performance/ },
    { name: "webkit", use: { ...devices["Desktop Safari"] }, testIgnore: /performance/, grepInvert: /@chromium-only/ },
    // Timing runs alone, after everything else, so other workers do not steal its CPU.
    {
      name: "performance",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /performance/,
      fullyParallel: false,
      dependencies: ["chromium", "mobile", "webkit"],
    },
  ],
});
