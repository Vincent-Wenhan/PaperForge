import { describe, it, expect, beforeEach } from "vitest";
import { useAppStore } from "@/lib/store";
import type { Run } from "@/lib/store";

const run: Run = {
  id: "run_1",
  title: "Test Run",
  status: "active",
  phase: "init",
  created_at: new Date().toISOString(),
};

beforeEach(() => {
  useAppStore.setState({
    currentRun: run,
    messages: [],
    attachments: [],
    isRunning: false,
  });
});

describe("Streaming message merge", () => {
  it("creates a placeholder streaming message on first delta", () => {
    useAppStore.getState().appendMessageDelta("msg_1", "Hello");
    const msgs = useAppStore.getState().messages;
    expect(msgs).toHaveLength(1);
    expect(msgs[0].id).toBe("msg_1");
    expect(msgs[0].content).toBe("Hello");
    expect(msgs[0].streaming).toBe(true);
    expect(msgs[0].status).toBe("streaming");
  });

  it("appends subsequent deltas to the same message", () => {
    useAppStore.getState().appendMessageDelta("msg_1", "Hello");
    useAppStore.getState().appendMessageDelta("msg_1", " world");
    useAppStore.getState().appendMessageDelta("msg_1", "!");
    const msgs = useAppStore.getState().messages;
    expect(msgs).toHaveLength(1);
    expect(msgs[0].content).toBe("Hello world!");
  });

  it("keeps separate messages separate by message_id", () => {
    useAppStore.getState().appendMessageDelta("msg_1", "A");
    useAppStore.getState().appendMessageDelta("msg_2", "B");
    useAppStore.getState().appendMessageDelta("msg_1", "C");
    const msgs = useAppStore.getState().messages;
    expect(msgs).toHaveLength(2);
    const msg1 = msgs.find((m) => m.id === "msg_1");
    const msg2 = msgs.find((m) => m.id === "msg_2");
    expect(msg1?.content).toBe("AC");
    expect(msg2?.content).toBe("B");
  });

  it("completeMessage finalizes the content", () => {
    useAppStore.getState().appendMessageDelta("msg_1", "Partial");
    useAppStore.getState().completeMessage("msg_1", "Partial complete");
    const msgs = useAppStore.getState().messages;
    expect(msgs).toHaveLength(1);
    expect(msgs[0].content).toBe("Partial complete");
    expect(msgs[0].streaming).toBe(false);
    expect(msgs[0].status).toBe("completed");
  });

  it("multiple deltas for unknown id create one placeholder, then append", () => {
    useAppStore.getState().appendMessageDelta("msg_99", "X");
    useAppStore.getState().appendMessageDelta("msg_99", "Y");
    const msgs = useAppStore.getState().messages;
    expect(msgs).toHaveLength(1);
    expect(msgs[0].content).toBe("XY");
  });
});
