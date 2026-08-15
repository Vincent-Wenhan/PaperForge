import { describe, expect, it } from "vitest";
import { projectToolActivities } from "../project-tools";
import type { Message } from "../store";

function msg(partial: Partial<Message> & { id: string; role: Message["role"] }): Message {
  return { content: "", ...partial } as Message;
}

describe("projectToolActivities", () => {
  it("projects tool calls and pairs each with its matching tool result", () => {
    const messages: Message[] = [
      msg({
        id: "m1",
        role: "assistant",
        task_id: "task_a",
        tool_calls: [
          { id: "call_1", name: "parse_paper", args: { pdf_path: "a.pdf" } },
          { id: "call_2", name: "plan_product", args: {} },
        ],
      }),
      msg({ id: "m2", role: "tool", task_id: "task_a", tool_call_id: "call_1", content: "{\"ok\":true}" }),
    ];

    const activities = projectToolActivities(messages);
    expect(activities).toHaveLength(2);

    const done = activities.find((a) => a.id === "call_1")!;
    expect(done.status).toBe("completed");
    expect(done.result).toBe('{"ok":true}');
    expect(done.args).toEqual({ pdf_path: "a.pdf" });

    const pending = activities.find((a) => a.id === "call_2")!;
    expect(pending.status).toBe("running");
    expect(pending.result).toBeUndefined();
  });

  it("yields no activities when there are no tool calls", () => {
    expect(projectToolActivities([msg({ id: "u", role: "user", content: "hi" })])).toHaveLength(0);
  });

  it("threads the originating task through each activity", () => {
    const messages: Message[] = [
      msg({ id: "m1", role: "assistant", task_id: "task_z", tool_calls: [{ id: "c9", name: "verify_app" }] }),
    ];
    const activities = projectToolActivities(messages);
    expect(activities[0].task_id).toBe("task_z");
  });
});
