import { test, expect } from "@playwright/test";

// Public pages render and auth-gated routes redirect. The waitlist form's
// submit path needs the API, so it is covered by the Python suite; here we
// check the page a visitor actually gets.

test("landing page renders", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: /shortlist/i })).toBeVisible();
  // Header "[Sign in]" and the footer link both go to sign-in.
  await expect(page.getByRole("link", { name: /Sign in/ }).first()).toBeVisible();
});

test("the waitlist form asks for all five fields", async ({ page }) => {
  await page.goto("/");
  const form = page.locator("form").first();
  await expect(form.getByLabel("Name", { exact: true })).toBeVisible();
  await expect(form.getByLabel("Work email")).toBeVisible();
  await expect(form.getByLabel("Title", { exact: true })).toBeVisible();
  await expect(form.getByLabel("Company", { exact: true })).toBeVisible();
  await expect(form.getByLabel("Industry", { exact: true })).toBeVisible();
  await expect(form.getByRole("button", { name: /Request access/ })).toBeVisible();
});

test("the page carries its differentiators and sections", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /somewhere you can't see/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: /a score can't tell you/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: /takes about an hour/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Before you ask/i })).toBeVisible();
});

test("element ids are unique across both copies of the form", async ({ page }) => {
  await page.goto("/");
  const duplicates = await page.evaluate(() => {
    const seen = new Set<string>();
    const dupes: string[] = [];
    for (const node of Array.from(document.querySelectorAll("[id]"))) {
      if (seen.has(node.id)) dupes.push(node.id);
      seen.add(node.id);
    }
    return dupes;
  });
  expect(duplicates).toEqual([]);
});

test("the landing page is black", async ({ page }) => {
  await page.goto("/");
  const background = await page
    .locator(".ep-landing")
    .evaluate((node) => getComputedStyle(node).backgroundColor);
  expect(background).toBe("rgb(0, 0, 0)");
});

test("dashboard redirects anonymous visitors to sign-in", async ({ page }) => {
  await page.goto("/dashboard");
  await page.waitForURL(/sign-in/);
});

test("admin redirects anonymous visitors to sign-in", async ({ page }) => {
  await page.goto("/admin");
  await page.waitForURL(/sign-in/);
});
