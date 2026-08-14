import type { RunEvent } from "./api";
import type { PreviewState, Task } from "./contracts";
import { enqueueMessageDelta, flushMessageDeltas } from "./realtime/stream-buffer";
import { useAppStore, type AgentStep, type Approval, type Event } from "./store";

export type ApplyRunEventResult = "applied" | "ignored" | "duplicate" | "gap";

// Workbench stays closed while the user pins it closed; otherwise preview.ready
// opens it and artifact/file events peek it.
export function inferWorkbenchMode(
  eventType: string,
  current: "closed" | "peek" | "open",
  pinnedClosed: boolean,
): "closed" | "peek" | "open" {
  if (pinnedClosed) return "closed";
  if (eventType === "preview.ready") return "open";
  if (eventType === "artifact.created" || eventType === "file.changed") {
    return current === "closed" ? "peek" : current;
  }
  return current;
}

function eventData(event: RunEvent): any {
  return event.payload ?? (event as { data?: any }).data ?? {};
}

function toStoreEvent(event: RunEvent, data: any): Event {
  return {
    id: event.id,
    type: event.type,
    data,
    run_id: event.run_id,
    ts: event.ts,
    seq: event.seq,
  };
}

function toTask(task: any, runId: string): Task {
  const id = task?.id ?? task?.task_id ?? "untracked";
  return {
    id,
    task_id: id,
    run_id: task?.run_id ?? runId,
    title: task?.title ?? null,
    goal: task?.goal ?? null,
    status: task?.status ?? "queued",
    phase: task?.phase,
    created_at: task?.created_at,
    updated_at: task?.updated_at,
    completed_at: task?.completed_at ?? null,
  };
}

// If a task.created/delta references a task we don't know yet, seed a minimal
// running task so projectTurns always has a home for it. The real task.created
// fills in the details onto the same id.
function ensureSyntheticTask(runId: string, taskId: string | undefined) {
  if (!taskId || taskId === "untracked") return;
  const store = useAppStore.getState();
  if (store.tasks.some((t) => t.id === taskId)) return;
  store.upsertTask({
    id: taskId,
    task_id: taskId,
    run_id: runId,
    title: null,
    goal: null,
    status: "queued",
  });
}

export function applyRunEvent(
  event: RunEvent,
  runId = useAppStore.getState().currentRun?.id,
): ApplyRunEventResult {
  const store = useAppStore.getState();
  if (!runId || event.run_id !== runId) return "duplicate";
  if (event.seq <= store.lastSeq) return "duplicate";
  if (store.lastSeq > 0 && event.seq > store.lastSeq + 1) return "gap";

  const data = eventData(event);
  const taskId = data.task_id ?? data.taskId ?? (event as { task_id?: string }).task_id ?? undefined;
  store.setLastSeq(event.seq);
  store.addEvent(toStoreEvent(event, data));
  const nextMode = inferWorkbenchMode(
    event.type,
    store.workbenchMode,
    store.workbenchPinnedClosed,
  );
  if (nextMode !== store.workbenchMode) store.setWorkbenchMode(nextMode);

  switch (event.type) {
    case "task.created":
      ensureSyntheticTask(runId, taskId);
      store.upsertTask(toTask(data.task, runId));
      return "applied";
    case "task.updated":
      ensureSyntheticTask(runId, taskId);
      store.upsertTask(toTask(data.task, runId));
      return "applied";
    case "task.completed":
      ensureSyntheticTask(runId, taskId);
      store.upsertTask(toTask(data.task, runId));
      return "applied";
    case "message.started":
      ensureSyntheticTask(runId, taskId);
      store.upsertMessage({
        id: data.message_id,
        public_id: data.message_id,
        role: "assistant",
        content: "",
        streaming: true,
        status: "streaming",
        task_id: taskId,
      });
      return "applied";
    case "message.delta":
      ensureSyntheticTask(runId, taskId);
      if (data.message_id) {
        enqueueMessageDelta(
          data.message_id,
          data.delta || data.text || "",
          taskId,
        );
      } else {
        store.appendAssistantDelta(data.text || data.delta || "");
      }
      return "applied";
    case "message.completed":
      flushMessageDeltas();
      if (data.message_id) {
        store.completeMessage(data.message_id, data.content || "");
      } else {
        store.finalizeStreamingAssistant();
      }
      return "applied";
    case "message.failed":
      if (data.message_id) {
        store.failMessage(data.message_id, data.error || "Message failed");
      }
      return "applied";
    case "tool.call":
    case "tool.result":
      return "applied";
    case "run.started":
      store.setIsRunning(true);
      return "applied";
    case "run.finished":
      store.finalizeStreamingAssistant();
      store.setIsRunning(false);
      return "applied";
    case "run.error":
      store.finalizeStreamingAssistant();
      store.setIsRunning(false);
      return "applied";
    case "run.status.changed":
      if (data.status) store.updateCurrentRun({ status: data.status });
      if (data.status === "running") store.setIsRunning(true);
      if (["done", "cancelled", "error"].includes(data.status)) store.setIsRunning(false);
      return "applied";
    case "run.updated":
      store.updateCurrentRun({
        ...(data.title ? { title: data.title } : {}),
        ...(data.status ? { status: data.status } : {}),
        ...(data.phase ? { phase: data.phase } : {}),
        ...(typeof data.pinned === "boolean" ? { pinned: data.pinned } : {}),
        ...(Object.prototype.hasOwnProperty.call(data, "archived_at")
          ? { archived_at: data.archived_at }
          : {}),
        ...(data.updated_at ? { updated_at: data.updated_at } : {}),
      });
      return "applied";
    case "task.phase.changed":
      if (data.phase) {
        store.updateCurrentRun({ phase: data.phase });
        const task: Task = {
          id: data.task_id || "current",
          task_id: data.task_id,
          run_id: runId,
          phase: data.phase,
          status: "running",
          updated_at: new Date().toISOString(),
        };
        store.upsertTask(task);
      }
      return "applied";
    case "step.started":
      store.upsertStep({
        id: data.step_id,
        task_id: data.task_id,
        kind: data.kind || "tool",
        title: data.title || "Running step",
        status: "running",
      });
      return "applied";
    case "step.progress":
      if (data.step_id) {
        store.upsertStep({
          id: data.step_id,
          status: "running",
          ...(typeof data.percent === "number" ? { percent: data.percent } : {}),
          ...(data.detail ? { detail: data.detail } : {}),
        });
      }
      return "applied";
    case "step.completed":
      if (data.step_id) {
        store.upsertStep({
          id: data.step_id,
          status: "completed",
          ...(data.summary ? { summary: data.summary } : {}),
        });
      }
      return "applied";
    case "step.failed":
      if (data.step_id) {
        store.upsertStep({
          id: data.step_id,
          status: "failed",
          ...(data.error ? { detail: data.error } : {}),
        });
      }
      return "applied";
    case "approval.requested":
      store.addPendingApproval({
        approval_id: data.approval_id,
        id: data.approval_id,
        run_id: runId,
        task_id: taskId,
        tool: data.tool || data.tool_name || "",
        tool_name: data.tool_name || data.tool || "",
        args: data.args || {},
        status: "pending",
      } satisfies Approval);
      return "applied";
    case "approval.resolved":
      store.resolvePendingApproval(data.approval_id, !!data.approved);
      return "applied";
    case "artifact.created":
      if (data.artifact_id) {
        store.addArtifact({
          id: data.artifact_id,
          run_id: runId,
          type: data.type || "artifact",
          path: data.path,
          task_id: taskId,
        });
      }
      return "applied";
    case "artifact.updated":
      if (data.artifact_id) {
        store.updateArtifact({
          id: data.artifact_id,
          data: data.data,
        });
      }
      return "applied";
    case "sandbox.started":
      store.setSandbox({
        id: data.sandbox_id,
        run_id: runId,
        container_id: data.container_id,
        preview_port: data.preview_port,
        environment: data.environment,
        preview_url: data.preview_url || null,
        error: data.error || null,
        status: "running",
      });
      return "applied";
    case "sandbox.error":
      store.setPreview({
        status: "degraded",
        sandbox_id: data.sandbox_id || store.sandbox?.id || null,
        error: data.error || "Sandbox error",
      } satisfies PreviewState);
      return "applied";
    case "preview.ready":
      store.setPreview({
        status: "running",
        sandbox_id: data.sandbox_id,
        preview_url: data.preview_url || null,
      } satisfies PreviewState);
      return "applied";
    case "stream.gap":
      return "gap";
    case "build.log.delta":
      if (data.text && data.step_id) {
        const existing = store.steps.find((s) => s.id === data.step_id);
        store.upsertStep({
          id: data.step_id,
          status: (existing?.status as AgentStep["status"]) || "running",
          detail: (existing?.detail || "") + data.text,
        });
      }
      return "applied";
    case "sandbox.log.delta":
      if (data.text) {
        store.appendSandboxLog({
          sandbox_id: data.sandbox_id,
          offset: data.offset || 0,
          stream: data.stream || "stdout",
          text: data.text,
        });
      }
      return "applied";
    default:
      return "ignored";
  }
}
