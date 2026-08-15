import type { Message } from "./store";

export interface ToolActivity {
  id: string;
  task_id?: string;
  name: string;
  args?: unknown;
  result?: string;
  status: "completed" | "running";
}

/** Project durable tool calls from assistant messages + their matching tool
 * results (doc 7.2). Does not add a table; the projection follows the existing
 * message rows via tool_call_id. */
export function projectToolActivities(messages: Message[]): ToolActivity[] {
  const results = new Map(
    messages
      .filter((m) => m.role === "tool" && m.tool_call_id)
      .map((m) => [m.tool_call_id!, m.content]),
  );

  return messages.flatMap((message) =>
    (message.tool_calls ?? []).map((call) => {
      const c = call as { id?: string; name?: string; args?: unknown };
      const id = c.id ?? `${message.id}-${c.name ?? ""}-${message.tool_calls!.indexOf(call)}`;
      return {
        id,
        task_id: message.task_id,
        name: c.name ?? "tool",
        args: c.args,
        result: results.get(id),
        status: results.has(id) ? "completed" : "running",
      };
    }),
  );
}
