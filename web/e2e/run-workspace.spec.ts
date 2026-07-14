import { expect, test } from "@playwright/test";

const run = {
  id: "run_e2e",
  title: "New Run",
  status: "active",
  phase: "init",
  pinned: false,
  archived_at: null,
  last_message_at: null,
  created_at: "2026-07-14T00:00:00Z",
  updated_at: "2026-07-14T00:00:00Z",
};

test("new run opens without a workspace 404", async ({ page }) => {
  const consoleErrors: string[] = [];
  const networkFailures: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    const errorText = request.failure()?.errorText || "failed";
    // Next.js cancels the previous RSC navigation request during a client
    // transition. That expected cancellation is not a failed application
    // request and should not make the smoke test flaky.
    if (errorText === "net::ERR_ABORTED" && request.url().includes("?_rsc=")) return;
    networkFailures.push(`${request.method()} ${request.url()}: ${errorText}`);
  });

  await page.route("**/api/library", async (route) => {
    await route.fulfill({ json: { papers: [] } });
  });
  await page.route("**/api/runs", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ json: run });
      return;
    }
    await route.fulfill({ json: [] });
  });
  await page.route("**/api/runs/run_e2e/state", async (route) => {
    await route.fulfill({
      json: {
        run,
        messages: [],
        artifacts: [],
        sandbox: null,
        preview: { status: "idle", sandbox_id: null },
        pending_approvals: [],
        approvals: [],
        tasks: [],
        event_cursor: 0,
      },
    });
  });
  await page.route("**/api/runs/run_e2e/events**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: ": connected\n\n",
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: /new run/i }).click();
  await expect(page).toHaveURL(/\/runs\/run_e2e$/);
  await expect(page.getByPlaceholder(/ask paperforge/i)).toBeVisible();
  await expect(page.getByRole("tab", { name: /preview/i })).toBeVisible();
  await expect(page.getByText(/404.*not found/i)).toHaveCount(0);

  expect(consoleErrors).toEqual([]);
  expect(networkFailures).toEqual([]);
});
