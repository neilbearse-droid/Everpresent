import { defineConfig } from "@playwright/test";

// Signed-in pages against a seeded API with Clerk stripped (CI job
// "signed-in-pages"; see scripts/e2e). The app must already be built with
// scripts/e2e/strip_clerk.py applied and API_ORIGIN pointing at the API.
export default defineConfig({
  testDir: "./e2e-signed-in",
  timeout: 60_000,
  workers: 2,
  use: {
    baseURL: "http://localhost:3000",
    launchOptions: {
      args: ["--proxy-bypass-list=<-loopback>"],
      ...(process.env.PLAYWRIGHT_CHROMIUM_PATH
        ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
        : {}),
    },
  },
  webServer: {
    command: "npm run start",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
