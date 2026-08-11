import type { Task } from "./contracts";
import type { AgentStep, Approval, Artifact, Message } from "./store";

export interface ConversationTurn {
  id: string;
  task: Task;
  userMessage: Message | null;
  assistantMessages: Message[];
  steps: AgentStep[];
  approvals: Approval[];
  artifacts: Artifact[];
  status: Task["status"];
}

function taskIdOf(item: { task_id?: string } | Approval | Artifact): string {
  return (item as { task_id?: string }).task_id ?? "untracked";
}

function groupByTask<T>(items: T[], getTaskId: (item: T) => string): Map<string, T[]> {
  const map = new Map<string, T[]>();
  for (const item of items) {
    const key = getTaskId(item);
    const group = map.get(key);
    if (group) group.push(item);
    else map.set(key, [item]);
  }
  return map;
}

/** Project messages/steps/approvals/artifacts per task into conversation turns
 * (doc 29). Untracked (pre-16) items fall into a single "untracked" turn. */
export function projectTurns(
  tasks: Task[],
  messages: Message[],
  steps: AgentStep[],
  approvals: Approval[],
  artifacts: Artifact[],
): ConversationTurn[] {
  const messageByTask = groupByTask(messages, taskIdOf);
  const stepByTask = groupByTask(steps, taskIdOf);
  const approvalByTask = groupByTask(approvals, taskIdOf);
  const artifactByTask = groupByTask(artifacts, taskIdOf);

  const turns: ConversationTurn[] = [];
  const seen = new Set<string>();

  for (const task of tasks) {
    const id = task.id ?? task.task_id ?? "";
    if (!id) continue;
    if (seen.has(id)) continue;
    seen.add(id);
    const taskMessages = messageByTask.get(id) || [];
    turns.push({
      id,
      task,
      userMessage: taskMessages.find((m) => m.role === "user") ?? null,
      assistantMessages: taskMessages.filter((m) => m.role === "assistant"),
      steps: stepByTask.get(id) || [],
      approvals: approvalByTask.get(id) || [],
      artifacts: artifactByTask.get(id) || [],
      status: task.status,
    });
  }

  // Any messages/steps not attributed to a known task still get a legacy turn
  // so old (pre-16) conversations are never silently dropped. New data
  // reaching this branch is a task_id regression, so warn in development.
  const untrackedItems = (messageByTask.get("untracked") || []).length
    + (stepByTask.get("untracked") || []).length
    + (approvalByTask.get("untracked") || []).length
    + (artifactByTask.get("untracked") || []).length;
  if (untrackedItems > 0) {
    if (process.env.NODE_ENV !== "production") {
      // eslint-disable-next-line no-console
      console.warn("Unexpected untracked conversation entities", untrackedItems);
    }
    turns.push({
      id: "untracked",
      task: { id: "untracked", status: "completed" },
      userMessage: (messageByTask.get("untracked") || []).find((m) => m.role === "user") ?? null,
      assistantMessages: (messageByTask.get("untracked") || []).filter((m) => m.role === "assistant"),
      steps: stepByTask.get("untracked") || [],
      approvals: approvalByTask.get("untracked") || [],
      artifacts: artifactByTask.get("untracked") || [],
      status: "completed",
    });
  }

  return turns;
}
