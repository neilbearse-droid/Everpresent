import { test, expect } from "@playwright/test";

// M0 e2e scope: the public pages render and auth-gated routes redirect.
// Signed-in flows need real Clerk keys and join the suite at M1.

test("landing page renders", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "EverPresent" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
});

test("dashboard redirects anonymous visitors to sign-in", async ({ page }) => {
  await page.goto("/dashboard");
  await page.waitForURL(/sign-in/);
});
