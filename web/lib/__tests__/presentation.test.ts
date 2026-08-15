import { describe, expect, it } from "vitest";
import { runStatusLabel, taskStatusLabel } from "../presentation";

describe("presentation mapper", () => {
  it("maps raw task statuses to product-level copy", () => {
    expect(taskStatusLabel("queued")).toBe("Preparing");
    expect(taskStatusLabel("running")).toBe("Working");
    expect(taskStatusLabel("waiting_approval")).toBe("Needs attention");
    expect(taskStatusLabel("waiting_tool")).toBe("Needs attention");
    expect(taskStatusLabel("waiting_input")).toBe("Needs attention");
    expect(taskStatusLabel("completed")).toBe("Completed");
    expect(taskStatusLabel("failed")).toBe("Failed");
    expect(taskStatusLabel("cancelled")).toBe("Cancelled");
  });

  it("never surfaces raw waiting_* tokens to the user", () => {
    const out = taskStatusLabel("waiting_approval");
    expect(out).not.toContain("waiting");
    expect(out.toLowerCase()).not.toContain("waiting");
  });

  it("defaults unknown / missing task statuses to Preparing", () => {
    expect(taskStatusLabel(undefined)).toBe("Preparing");
    expect(taskStatusLabel(null)).toBe("Preparing");
    expect(taskStatusLabel("")).toBe("Preparing");
  });

  it("maps run statuses and passes through unknown labels", () => {
    expect(runStatusLabel("running")).toBe("Running");
    expect(runStatusLabel("completed")).toBe("Completed");
    expect(runStatusLabel("active")).toBe("Active");
    expect(runStatusLabel("custom_status")).toBe("custom_status");
  });
});
