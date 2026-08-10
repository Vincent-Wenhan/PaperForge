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

  // Any messages/steps not attributed to a known task still get a turn so the
  // conversation is never silently dropped.
  for (const id of ["untracked"]) {
    const remaining = messageByTask.get(id)?.length
      || stepByTask.get(id)?.length
      || approvalByTask.get(id)?.length
      || artifactByTask.get(id)?.length;
    if (remaining) {
      turns.push({
        id,
        task: { id, status: "completed" },
        userMessage: (messageByTask.get(id) || []).find((m) => m.role === "user") ?? null,
        assistantMessages: (messageByTask.get(id) || []).filter((m) => m.role === "assistant"),
        steps: stepByTask.get(id) || [],
        approvals: approvalByTask.get(id) || [],
        artifacts: artifactByTask.get(id) || [],
        status: "completed",
      });
    }
  }

  return turns;
}
