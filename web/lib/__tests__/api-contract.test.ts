import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, SSEClient } from "../api";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  listeners: Record<string, (event: MessageEvent) => void> = {};
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, handler: (event: MessageEvent) => void) {
    this.listeners[type] = handler;
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.restoreAllMocks();
});

describe("API contracts", () => {
  it("preserves structured backend errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({ code: "approval_conflict", detail: "Already resolved" }),
            { status: 409, headers: { "Content-Type": "application/json" } },
          ),
        ),
      ),
    );

    await expect(api.listApprovals("run_1")).rejects.toMatchObject({
      status: 409,
      code: "approval_conflict",
      detail: "Already resolved",
    });
    await expect(api.listApprovals("run_1")).rejects.toBeInstanceOf(ApiError);
  });

  it("connects SSE from a durable cursor", () => {
    const client = new SSEClient();
    client.connect("run_1", 17);

    expect(FakeEventSource.instances[0].url).toContain(
      "/api/runs/run_1/events?after_seq=17",
    );
  });

  it("hydrates the task list from the canonical state endpoint", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            run: { id: "run_1" },
            messages: [],
            artifacts: [],
            sandbox: null,
            pending_approvals: [],
            approvals: [],
            tasks: [{ id: "task_1", status: "running" }],
            event_cursor: 4,
          }),
          { status: 200 },
        ),
      ),
    );

    const state = await api.getRunState("run_1");
    expect(state.tasks[0].id).toBe("task_1");
    expect(state.event_cursor).toBe(4);
  });
});
