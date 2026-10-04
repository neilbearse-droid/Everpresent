import { expect, test } from "@playwright/test";

// Every signed-in page, rendered against a seeded API (scripts/e2e). Catches
// pages that crash, show an error state, or throw in the browser.
const PAGES = [
  "/dashboard",
  "/dashboard/scorecard",
  "/dashboard/answers",
  "/dashboard/engines",
  "/dashboard/queries",
  "/dashboard/citations",
  "/dashboard/pages",
  "/dashboard/agents",
  "/dashboard/recommendations",
  "/dashboard/outcome",
  "/dashboard/brand",
  "/dashboard/personas",
  "/dashboard/fanout",
  "/dashboard/whitespace",
  "/dashboard/action-plan",
  "/dashboard/runs",
  "/admin",
  "/admin/godaddy",
];

const BROKEN = [
  "Application error",
  "Internal Server Error",
  "API unreachable",
  "Unhandled Runtime Error",
  "This page could not be found",
  "No organization selected",
  "Can't reach the EverPresent API",
  "Could not load",
];

for (const path of PAGES) {
  test(`renders ${path}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const res = await page.goto(path, { waitUntil: "networkidle" });
    expect(res?.status(), `${path} HTTP status`).toBeLessThan(400);
    const body = await page.locator("body").innerText();
    for (const marker of BROKEN) expect(body, `${path} shows "${marker}"`).not.toContain(marker);
    await expect(page.locator("main").first()).toBeVisible();
    expect(errors, `${path} browser errors`).toEqual([]);
  });
}

test("overview shows the weekly briefing with seeded data", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByText("Are we winning?")).toBeVisible();
  await expect(page.getByText("This week")).toBeVisible();
});

test("outcome shows proof for the seeded fix", async ({ page }) => {
  await page.goto("/dashboard/outcome");
  await expect(page.getByText("Comparison table on the domains page")).toBeVisible();
});
