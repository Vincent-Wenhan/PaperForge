import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { getRunState, instances } = vi.hoisted(() => ({
  getRunState: vi.fn(),
  instances: [] as Array<{ connect: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> }>,
}));

vi.mock("../api", () => ({
  api: {
    getRunState,
  },
  SSEClient: class {
    connect = vi.fn();
    disconnect = vi.fn();
    on = vi.fn();
    constructor() {
      instances.push(this);
    }
  },
}));

import { useRunSession } from "../useRunSession";
import { useAppStore } from "../store";

beforeEach(() => {
  instances.length = 0;
  getRunState.mockReset();
  getRunState.mockResolvedValue({
    run: {
      id: "run_1",
      title: "Run",
      status: "active",
      created_at: "now",
      updated_at: "now",
    },
    messages: [],
    artifacts: [],
    sandbox: null,
    pending_approvals: [],
    approvals: [],
    tasks: [],
    event_cursor: 8,
  });
  useAppStore.setState({ currentRun: null, lastSeq: 0, sessionError: null } as any);
});

describe("run session", () => {
  it("hydrates once for a run id and connects from the durable cursor", async () => {
    const { rerender } = renderHook(({ runId }) => useRunSession(runId), {
      initialProps: { runId: "run_1" },
    });

    await waitFor(() => expect(getRunState).toHaveBeenCalledTimes(1));
    expect(instances).toHaveLength(1);
    expect(instances[0].connect).toHaveBeenCalledWith("run_1", 8);

    rerender({ runId: "run_1" });
    await act(async () => {});
    expect(getRunState).toHaveBeenCalledTimes(1);
  });
});
