import type { RunEvent } from "./api";
import type { PreviewState, Task } from "./contracts";
import { useAppStore, type Approval, type Event } from "./store";

export type ApplyRunEventResult = "applied" | "duplicate" | "gap" | "unknown";

function eventData(event: RunEvent): any {
  return event.payload ?? (event as any).data ?? {};
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

export function applyRunEvent(
  event: RunEvent,
  runId = useAppStore.getState().currentRun?.id,
): ApplyRunEventResult {
  const store = useAppStore.getState();
  if (!runId || event.run_id !== runId) return "duplicate";
  if (event.seq <= store.lastSeq) return "duplicate";
  if (store.lastSeq > 0 && event.seq > store.lastSeq + 1) return "gap";

  const data = eventData(event);
  store.setLastSeq(event.seq);
  store.addEvent(toStoreEvent(event, data));

  switch (event.type) {
    case "message.started":
      store.upsertMessage({
        id: data.message_id,
        public_id: data.message_id,
        role: "assistant",
        content: "",
        streaming: true,
        status: "streaming",
      });
      return "applied";
    case "message.delta":
      if (data.message_id) {
        store.appendMessageDelta(data.message_id, data.delta || data.text || "");
      } else {
        store.appendAssistantDelta(data.text || data.delta || "");
      }
      return "applied";
    case "message.completed":
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
    case "approval.requested":
      store.addPendingApproval({
        approval_id: data.approval_id,
        id: data.approval_id,
        run_id: runId,
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
      return "unknown";
    default:
      return "unknown";
  }
}
