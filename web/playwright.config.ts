import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      // Real FastAPI backend on the local_test provider so the no-mock
      // realtime spec can drive real SQLite + SSE (doc 5.12). Playwright
      // launches webServers from the config dir (web/), so cd to the repo
      // root to resolve the `api` package and the ./data DB path.
      command:
        "cd .. && python -m uvicorn api.main:app --host 127.0.0.1 --port 8000",
      url: "http://127.0.0.1:8000/api/runs",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      cwd: "./",
      env: {
        ...process.env,
        LLM_PROVIDER: "local_test",
        DB_PATH: "./data/e2e.db",
      },
    },
    {
      command: "npm run dev -- -p 3100",
      url: "http://127.0.0.1:3100/",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      cwd: "./",
    },
  ],
});
