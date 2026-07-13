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
  useAppStore.setState({ currentRun: run, isRunning: false });
});

describe("Task timeline state", () => {
  it("updates run phase via updateCurrentRun", () => {
    useAppStore.getState().updateCurrentRun({ phase: "parsing" });
    expect(useAppStore.getState().currentRun?.phase).toBe("parsing");
  });

  it("updates run status via updateRunStatus", () => {
    useAppStore.getState().updateRunStatus("running");
    expect(useAppStore.getState().currentRun?.status).toBe("running");
  });

  it("phase transitions: init → parsing → composing → planning → generating → verifying → done", () => {
    const phases = ["parsing", "composing", "planning", "generating", "verifying", "done"];
    for (const phase of phases) {
      useAppStore.getState().updateCurrentRun({ phase });
      expect(useAppStore.getState().currentRun?.phase).toBe(phase);
    }
  });

  it("updates currentRun status from SSE run.status.changed event", () => {
    useAppStore.getState().updateCurrentRun({ status: "completed" });
    expect(useAppStore.getState().currentRun?.status).toBe("completed");
  });
});
