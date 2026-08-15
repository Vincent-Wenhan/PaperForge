import { beforeAll, beforeEach, describe, expect, it } from "vitest";

import { flushMessageDeltas } from "../realtime/stream-buffer";
import { applyRunEvent, inferWorkbenchMode } from "../run-events";
import { useAppStore } from "../store";
import { isKnownRunEvent } from "../api";

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
        version: 2,
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
        version: 2,
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
      version: 2,
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
      version: 2,
      id: "e1",
      seq: 1,
      run_id: "run_1",
      type: "step.started",
      ts: "now",
      payload: { step_id: "step_1", kind: "codegen", title: "Generating" },
    });
    applyRunEvent({
      version: 2,
      id: "e2",
      seq: 2,
      run_id: "run_1",
      type: "step.progress",
      ts: "now",
      payload: { step_id: "step_1", percent: 50 },
    });
    applyRunEvent({
      version: 2,
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

  it("infers workbench mode from preview/artifact events, respecting pinned closed", () => {
    expect(inferWorkbenchMode("artifact.created", "closed", false)).toBe("peek");
    expect(inferWorkbenchMode("preview.ready", "peek", false)).toBe("open");
    expect(inferWorkbenchMode("preview.ready", "closed", true)).toBe("closed");
    expect(inferWorkbenchMode("message.delta", "open", false)).toBe("open");
  });

  it("ignores unknown future events without rehydrating (doc 23.7)", () => {
    useAppStore.setState({ lastSeq: 10 });
    const result = applyRunEvent({
      version: 2,
      id: "evt_11",
      seq: 11,
      run_id: "run_1",
      type: "future.event",
      ts: Date.now(),
      payload: {},
    });
    // Unknown future events collapse to the same "ignored" verdict as the
    // reducer's default branch, so the seq still advances without rehydration.
    expect(result).toBe("ignored");
    expect(useAppStore.getState().lastSeq).toBe(11);
  });

  it("detects a real sequence gap (doc 23.8)", () => {
    useAppStore.setState({ lastSeq: 10 });
    const result = applyRunEvent({
      version: 2,
      id: "evt_12",
      seq: 12,
      run_id: "run_1",
      type: "message.delta",
      ts: Date.now(),
      payload: { message_id: "msg_1", delta: "x" },
    });
    expect(result).toBe("gap");
  });

  it("handles task.created before message deltas (SSE ordering race)", () => {
    applyRunEvent({
      version: 2,
      id: "e1",
      seq: 1,
      run_id: "run_1",
      type: "task.created",
      ts: "now",
      payload: { task: { id: "task_alpha", run_id: "run_1", title: "Alpha", status: "queued", phase: "init" } },
    });
    // A delta references the task; the placeholder message must carry task_id.
    applyRunEvent({
      version: 2,
      id: "e2",
      seq: 2,
      run_id: "run_1",
      type: "message.delta",
      ts: "now",
      payload: { message_id: "msg_a", delta: "hi", task_id: "task_alpha" },
    });
    flushMessageDeltas();

    const tasks = useAppStore.getState().tasks;
    expect(tasks.some((t) => t.id === "task_alpha")).toBe(true);
    const msg = useAppStore.getState().messages.find((m) => m.id === "msg_a");
    expect(msg?.task_id).toBe("task_alpha");
  });

  it("creates a synthetic task for deltas referencing an unknown task", () => {
    applyRunEvent({
      version: 2,
      id: "e1",
      seq: 1,
      run_id: "run_1",
      type: "message.delta",
      ts: "now",
      payload: { message_id: "msg_b", delta: "hello", task_id: "task_beta" },
    });
    flushMessageDeltas();
    const tasks = useAppStore.getState().tasks;
    expect(tasks.some((t) => t.id === "task_beta")).toBe(true);
  });

  it("routes task.updated and task.completed into the task list", () => {
    applyRunEvent({
      version: 2,
      id: "e1",
      seq: 1,
      run_id: "run_1",
      type: "task.updated",
      ts: "now",
      payload: { task: { id: "task_g", run_id: "run_1", status: "running", phase: "init" } },
    });
    applyRunEvent({
      version: 2,
      id: "e2",
      seq: 2,
      run_id: "run_1",
      type: "task.completed",
      ts: "now",
      payload: { task: { id: "task_g", run_id: "run_1", status: "completed" } },
    });

    const task = useAppStore.getState().tasks.find((t) => t.id === "task_g");
    expect(task?.status).toBe("completed");
  });

  it("streams build log deltas onto the step detail (doc 19.3)", () => {
    applyRunEvent({
      version: 2,
      id: "e1",
      seq: 1,
      run_id: "run_1",
      type: "step.started",
      ts: "now",
      payload: { step_id: "step_b", kind: "build", title: "Building" },
    });
    applyRunEvent({
      version: 2,
      id: "e2",
      seq: 2,
      run_id: "run_1",
      type: "build.log.delta",
      ts: "now",
      payload: { step_id: "step_b", text: "Compiled successfully." },
    });
    applyRunEvent({
      version: 2,
      id: "e3",
      seq: 3,
      run_id: "run_1",
      type: "build.log.delta",
      ts: "now",
      payload: { step_id: "step_b", text: "next build" },
    });

    const step = useAppStore.getState().steps.find((s) => s.id === "step_b");
    expect(step?.detail).toBe("Compiled successfully.next build");
    expect(step?.status).toBe("running");
  });

  it("narrows known versus unknown events via the type guard", () => {
    expect(isKnownRunEvent({ type: "message.delta" } as any)).toBe(true);
    expect(isKnownRunEvent({ type: "task.created" } as any)).toBe(true);
    expect(isKnownRunEvent({ type: "future.event" } as any)).toBe(false);
    expect(isKnownRunEvent({ type: "approval.requested" } as any)).toBe(true);
    expect(isKnownRunEvent({ type: "totally.unknown" } as any)).toBe(false);
  });

  it("routes unknown events only into the debug buffer, never main state", () => {
    useAppStore.setState({ tasks: [], steps: [], messages: [], lastSeq: 5 });
    const result = applyRunEvent({
      version: 2,
      id: "evt_unknown",
      seq: 6,
      run_id: "run_1",
      type: "brand.new.event",
      ts: Date.now(),
      payload: { some: "payload", task_id: "task_ghost" },
    });

    // Cursor advances and a debug event is buffered, but no task/message/step
    // and no workbench change happen for an event the client doesn't know.
    expect(result).toBe("ignored");
    expect(useAppStore.getState().lastSeq).toBe(6);
    expect(useAppStore.getState().events.some((e) => e.type === "brand.new.event")).toBe(true);
    expect(useAppStore.getState().tasks.some((t) => t.id === "task_ghost")).toBe(false);
    expect(useAppStore.getState().messages.length).toBe(0);
    expect(useAppStore.getState().steps.length).toBe(0);
  });
});
