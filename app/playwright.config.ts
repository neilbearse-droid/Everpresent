import { defineConfig } from "@playwright/test";

// Placeholder Clerk keys: enough for the middleware to boot and for anonymous
// redirects to work. Production-style (pk_live) so Clerk's dev-instance
// browser handshake never redirects anonymous page loads to clerk.example.com.
// Signed-in e2e flows (M1+) override these with real test keys via the env.
const PLACEHOLDER_PUBLISHABLE_KEY = "pk_live_Y2xlcmsuZXhhbXBsZS5jb20k";
const PLACEHOLDER_SECRET_KEY = "sk_live_placeholder";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:3000",
    launchOptions: {
      // Never route localhost through an ambient HTTPS proxy (sandbox setups).
      args: ["--proxy-bypass-list=<-loopback>"],
      // Some sandboxes pre-install a Chromium whose build number differs from
      // this @playwright/test pin; point at it when provided instead of
      // re-downloading. CI leaves this unset and uses `playwright install`.
      ...(process.env.PLAYWRIGHT_CHROMIUM_PATH
        ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
        : {}),
    },
  },
  webServer: {
    command: "npm run start",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    env: {
      NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY:
        process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? PLACEHOLDER_PUBLISHABLE_KEY,
      CLERK_SECRET_KEY: process.env.CLERK_SECRET_KEY ?? PLACEHOLDER_SECRET_KEY,
      NEXT_PUBLIC_CLERK_SIGN_IN_URL: "/sign-in",
    },
  },
});
