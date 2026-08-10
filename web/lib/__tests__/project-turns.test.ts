import { describe, expect, it } from "vitest";
import { projectTurns } from "../project-turns";
import type { Task } from "../contracts";
import type { AgentStep, Approval, Artifact, Message } from "../store";

function task(id: string, status = "completed"): Task {
  return { id, task_id: id, status };
}

function msg(id: string, role: Message["role"], task_id: string): Message {
  return { id, public_id: id, role, content: "", task_id };
}

describe("projectTurns", () => {
  it("groups messages/steps/approvals/artifacts per task", () => {
    const tA = task("task_a");
    const tB = task("task_b");
    const messages: Message[] = [msg("m1", "user", "task_a"), msg("m2", "assistant", "task_a")];
    const steps: AgentStep[] = [
      { id: "s1", task_id: "task_a", title: "Read", status: "completed" },
      { id: "s2", task_id: "task_b", title: "Plan", status: "running" },
    ];
    const approvals: Approval[] = [
      { approval_id: "ap1", task_id: "task_a", tool: "generate_nextjs_app", args: {}, status: "pending" },
    ];
    const artifacts: Artifact[] = [
      { id: "ar1", task_id: "task_a", type: "nextjs_app" },
    ];

    const turns = projectTurns([tA, tB], messages, steps, approvals, artifacts);
    expect(turns).toHaveLength(2);

    const a = turns.find((t) => t.id === "task_a")!;
    expect(a.userMessage?.id).toBe("m1");
    expect(a.assistantMessages).toHaveLength(1);
    expect(a.steps.map((s) => s.id)).toEqual(["s1"]);
    expect(a.approvals).toHaveLength(1);
    expect(a.artifacts).toHaveLength(1);

    const b = turns.find((t) => t.id === "task_b")!;
    expect(b.steps.map((s) => s.id)).toEqual(["s2"]);
  });

  it("collects untracked items into a single turn", () => {
    const messages: Message[] = [msg("m1", "user", "untracked")];
    const steps: AgentStep[] = [
      { id: "s1", title: "Old", status: "completed" },
    ];
    const turns = projectTurns([], messages, steps, [], []);
    expect(turns).toHaveLength(1);
    expect(turns[0].id).toBe("untracked");
    expect(turns[0].steps).toHaveLength(1);
  });
});
