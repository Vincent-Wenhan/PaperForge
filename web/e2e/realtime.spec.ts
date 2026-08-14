import { expect, test, type Page, type APIRequestContext } from "@playwright/test";

// Real-time mainline test with NO /state mocking (doc 5.12 / 5.13).
// Drives real FastAPI + SQLite + SSE via the local_test provider. Proves
// that sending a message shows the assistant reply WITHOUT a page refresh —
// the DB -> SSE -> Store -> Turn -> UI chain all live.
//
// Runs isolated from the mocked specs because it needs a real backend.

const unique = () => `pw_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

async function createTestRun(request: APIRequestContext): Promise<string> {
  const resp = await request.post("/api/runs", {
    data: {
      title: `realtime e2e ${unique()}`,
    },
  });
  expect(resp.ok()).toBeTruthy();
  const run = await resp.json();
  return run.id;
}

test("new assistant reply appears without reload", async ({ page, request }) => {
  test.setTimeout(60_000);
  const runId = await createTestRun(request);
  await page.goto(`/runs/${runId}`);

  // Wait for real hydration + a real SSE connection.
  const composer = page.getByPlaceholder(/Ask PaperForge/i).first();
  await expect(composer).toBeVisible({ timeout: 15_000 });

  // Resolve unhandled peer connections: EventSource URLs are cryptographically
  // signed, so the WebSocket/EventSource handshake target won't match the
  // page URL. Ignore the resulting certificate errors.
  page.on("serviceworker", () => {});
  page.context().on("weberror", (err) => {
    // eslint-disable-next-line no-console
    console.log("[weberror]", err.error()?.message);
  });

  await composer.fill("stream-test");
  await page.getByRole("button", { name: "Send" }).click();

  // The mock-free backend replies "stream-test-response for: stream-test"
  // through a REAL message.delta SSE stream — no refresh, no /state mock.
  await expect(page.getByText(/stream-test-response/)).toBeVisible({
    timeout: 20_000,
  });
});

test("reply survives a reload with identical content", async ({ page, request }) => {
  const runId = await createTestRun(request);
  await page.goto(`/runs/${runId}`);

  const composer = page.getByPlaceholder(/Ask PaperForge/i).first();
  await expect(composer).toBeVisible({ timeout: 15_000 });

  await composer.fill("stream-test");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(/stream-test-response/)).toBeVisible({
    timeout: 15_000,
  });

  const before = await page.getByText(/stream-test-response/).allTextContents();

  await page.reload();
  await expect(page.getByText(/stream-test-response/)).toBeVisible({
    timeout: 15_000,
  });
  const after = await page.getByText(/stream-test-response/).allTextContents();

  // Refresh must not duplicate the reply (doc 5.13: turn/message parity).
  expect(before.length).toBeGreaterThan(0);
  expect(after).toEqual(before);
});
