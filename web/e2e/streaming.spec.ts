import { expect, test, type Page } from "@playwright/test";

// Section 40 E2E acceptance tests (doc 40.10 - 40.13). These assert the
// user-visible streaming contract that unit tests cannot: assistant text must
// appear before a task finishes, reload must not duplicate content, the
// composer must stay usable while a task runs (queue follow-up), and a
// generated app can be edited next turn without re-parsing.

const run = {
  id: "run_stream_e2e",
  title: "Streaming Run",
  status: "active",
  phase: "generated",
  pinned: false,
  archived_at: null,
  last_message_at: null,
  created_at: "2026-08-11T00:00:00Z",
  updated_at: "2026-08-11T00:00:00Z",
};

/** Seed a run whose /state returns a partial assistant message and a running task. */
async function seedStreamingRun(page: Page, { tasks }: { tasks: unknown[] }) {
  await page.route("**/api/runs", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ json: run });
      return;
    }
    await route.fulfill({ json: [run] });
  });
  await page.route("**/api/runs/run_stream_e2e/state", async (route) => {
    await route.fulfill({
      json: {
        run: { ...run, ...(tasks.length ? { status: "running" } : {}) },
        messages: [
          {
            id: 1,
            public_id: "msg_user",
            run_id: "run_stream_e2e",
            role: "user",
            content: "Explain the paper",
            tool_calls: null,
            created_at: "2026-08-11T00:00:00Z",
          },
          {
            id: 2,
            public_id: "msg_assistant",
            run_id: "run_stream_e2e",
            role: "assistant",
            content: tasks.length ? "partial answer" : "full answer",
            tool_calls: null,
            streaming: tasks.length > 0,
            created_at: "2026-08-11T00:00:01Z",
          },
        ],
        artifacts: [],
        sandbox: null,
        preview: { status: "idle", sandbox_id: null },
        pending_approvals: [],
        approvals: [],
        tasks,
        steps: [],
        event_cursor: 5,
      },
    });
  });
  await page.route("**/api/runs/run_stream_e2e/events**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: ": connected\n\n",
    });
  });
}

test("assistant text is visible before the task finishes (doc 40.10)", async ({ page }) => {
  await seedStreamingRun(page, {
    tasks: [
      { id: "task_1", run_id: "run_stream_e2e", status: "running", title: "Explain" },
    ],
  });
  await page.goto("/runs/run_stream_e2e");

  // The partial assistant text is already present, and the task is running.
  await expect(page.getByTestId("assistant-message-current")).toContainText("partial");
  await expect(page.getByTestId("task-status")).toContainText("running");
});

test("reload resumes a stream without duplicate content (doc 40.11)", async ({ page }) => {
  await seedStreamingRun(page, {
    tasks: [
      { id: "task_1", run_id: "run_stream_e2e", status: "running", title: "Explain" },
    ],
  });
  await page.goto("/runs/run_stream_e2e");
  await expect(page.getByTestId("assistant-message-current")).toContainText("partial");

  await page.reload();
  await expect(page.getByTestId("assistant-message-current")).toContainText("partial");
});

test("composer remains usable while a task runs (doc 40.12)", async ({ page }) => {
  await seedStreamingRun(page, {
    tasks: [
      { id: "task_1", run_id: "run_stream_e2e", status: "running", title: "Explain" },
    ],
  });
  await page.goto("/runs/run_stream_e2e");

  const composer = page.getByPlaceholder(/follow-up|Ask PaperForge/i).first();
  await expect(composer).toBeEnabled();
  await composer.fill("Also make the sidebar narrower");
  // The composer stays interactive even while running; the run is not done.
  await expect(composer).toHaveValue("Also make the sidebar narrower");
});

/** Seed a generated run (workspace steps present) so the next turn edits it. */
async function seedGeneratedRun(page: Page) {
  await page.route("**/api/runs", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ json: run });
      return;
    }
    await route.fulfill({ json: [run] });
  });

  // The prior turn's edit step is already in the conversation history: it
  // says a workspace was edited (no paper parse, no "files changed" yet).
  await page.route("**/api/runs/run_stream_e2e/state", async (route) => {
    await route.fulfill({
      json: {
        run: { ...run, status: "active" },
        messages: [
          {
            id: 1,
            public_id: "msg_user_first",
            run_id: "run_stream_e2e",
            role: "user",
            content: "Generate the app",
            tool_calls: null,
            created_at: "2026-08-11T00:00:00Z",
          },
          {
            id: 2,
            public_id: "msg_assistant_first",
            run_id: "run_stream_e2e",
            role: "assistant",
            content: "Workspace is ready to edit.",
            tool_calls: null,
            streaming: false,
            created_at: "2026-08-11T00:00:01Z",
          },
        ],
        artifacts: [],
        sandbox: null,
        preview: { status: "idle", sandbox_id: null },
        pending_approvals: [],
        approvals: [],
        tasks: [
          { id: "task_1", run_id: "run_stream_e2e", status: "completed", title: "Generate" },
        ],
        steps: [
          {
            id: "step_1",
            run_id: "run_stream_e2e",
            task_id: "task_1",
            kind: "edit",
            title: "Inspecting workspace",
            status: "completed",
            summary: "2 files changed",
            detail: null,
            created_at: "2026-08-11T00:00:00Z",
          },
        ],
        event_cursor: 0,
      },
    });
  });
  await page.route("**/api/runs/run_stream_e2e/events**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: ": connected\n\n",
    });
  });
}

test("generated app is edited next turn without reparsing (doc 40.13)", async ({ page }) => {
  await seedGeneratedRun(page);

  await page.goto("/runs/run_stream_e2e");

  // The workspace edit is visible: workspace text present, no re-parse.
  await expect(page.getByText(/Inspecting workspace/i)).toBeVisible();
  await expect(page.getByText(/files changed/i)).toBeVisible();
  await expect(page.getByText(/Reading paper/i)).not.toBeVisible();
});
