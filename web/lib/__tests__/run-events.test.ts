import { beforeAll, beforeEach, describe, expect, it } from "vitest";

import { flushMessageDeltas } from "../realtime/stream-buffer";
import { applyRunEvent } from "../run-events";
import { useAppStore } from "../store";

beforeEach(() => {
  useAppStore.setState({
    currentRun: {
      id: "run_1",
      title: "Run",
      status: "running",
      created_at: "now",
      updated_at: "now",
    },
    messages: [],
    events: [],
    pendingApprovals: [],
    artifacts: [],
    tasks: [],
    sandbox: null,
    preview: null,
    lastSeq: 0,
    sessionError: null,
  } as any);
});

describe("run event reducer", () => {
  it("applies ordered events once and advances the cursor", () => {
    expect(
      applyRunEvent({
        version: 1,
        id: "evt_1",
        seq: 1,
        run_id: "run_1",
        type: "message.delta",
        ts: "now",
        payload: { message_id: "msg_1", delta: "Hello" },
      }),
    ).toBe("applied");
    // Deltas are batched per-frame; flush so the test observes the application.
    flushMessageDeltas();

    expect(
      applyRunEvent({
        version: 1,
        id: "evt_1",
        seq: 1,
        run_id: "run_1",
        type: "message.delta",
        ts: "now",
        payload: { message_id: "msg_1", delta: "duplicate" },
      }),
    ).toBe("duplicate");

    expect(useAppStore.getState().messages[0].content).toBe("Hello");
    expect(useAppStore.getState().lastSeq).toBe(1);
  });

  it("requests hydration when an event cursor has a gap", () => {
    useAppStore.getState().setLastSeq(2);
    const result = applyRunEvent({
      version: 1,
      id: "evt_4",
      seq: 4,
      run_id: "run_1",
      type: "run.status.changed",
      ts: "now",
      payload: { status: "done" },
    });

    expect(result).toBe("gap");
    expect(useAppStore.getState().currentRun?.status).toBe("running");
  });

  it("applies step lifecycle events into the steps list", () => {
    applyRunEvent({
      version: 1,
      id: "e1",
      seq: 1,
      run_id: "run_1",
      type: "step.started",
      ts: "now",
      payload: { step_id: "step_1", kind: "codegen", title: "Generating" },
    });
    applyRunEvent({
      version: 1,
      id: "e2",
      seq: 2,
      run_id: "run_1",
      type: "step.progress",
      ts: "now",
      payload: { step_id: "step_1", percent: 50 },
    });
    applyRunEvent({
      version: 1,
      id: "e3",
      seq: 3,
      run_id: "run_1",
      type: "step.completed",
      ts: "now",
      payload: { step_id: "step_1", summary: "done" },
    });

    const step = useAppStore.getState().steps[0];
    expect(step.id).toBe("step_1");
    expect(step.status).toBe("completed");
    expect(step.summary).toBe("done");
  });
});
