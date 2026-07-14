import { beforeEach, describe, expect, it } from "vitest";

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
        id: "evt_1",
        seq: 1,
        run_id: "run_1",
        type: "message.delta",
        ts: "now",
        payload: { message_id: "msg_1", delta: "Hello" },
      }),
    ).toBe("applied");

    expect(
      applyRunEvent({
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
});
