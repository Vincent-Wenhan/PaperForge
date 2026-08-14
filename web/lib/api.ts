import type { ApiApproval, ApiArtifact, ApiMessage, ApiPaper, ApiRun, ApiSandbox, ApiTask } from "./api/types";
import type { RunSession, Task } from "./contracts";
export type { ApiTask } from "./api/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

export function buildUrl(path: string): string {
  if (API_BASE) return `${API_BASE}${path}`;
  return path;
}

export function buildPaperPdfUrl(paperId: string): string {
  return buildUrl(`/api/library/${paperId}/pdf`);
}

export function triggerBrowserDownload(blob: Blob, filename: string): void {
  if (typeof window === "undefined" || typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly detail: unknown;
  readonly payload: unknown;

  constructor(
    status: number,
    detail: unknown,
    code?: string,
    payload?: unknown,
  ) {
    const message = typeof detail === "string" ? detail : `Request failed (${status})`;
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.payload = payload;
  }

  get userMessage(): string {
    if (this.status === 404) return "The requested resource was not found.";
    if (this.status >= 500) return "PaperForge encountered a server error. Please retry.";
    return this.message;
  }
}

async function apiErrorFromResponse(resp: Response): Promise<ApiError> {
  const raw = await resp.text();
  let payload: any = raw;
  try {
    payload = raw ? JSON.parse(raw) : {};
  } catch {
    // Keep the raw response as the detail below.
  }
  const detail = payload && typeof payload === "object"
    ? payload.detail ?? payload.error ?? raw
    : raw;
  const code = payload && typeof payload === "object" ? payload.code : undefined;
  return new ApiError(resp.status, detail || resp.statusText, code, payload);
}

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(buildUrl(path));
  if (!resp.ok) {
    throw await apiErrorFromResponse(resp);
  }
  return resp.json() as Promise<T>;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(buildUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    throw await apiErrorFromResponse(resp);
  }
  return resp.json() as Promise<T>;
}

async function deleteJson<T>(path: string): Promise<T> {
  const resp = await fetch(buildUrl(path), { method: "DELETE" });
  if (!resp.ok) {
    throw await apiErrorFromResponse(resp);
  }
  return resp.json() as Promise<T>;
}

async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(buildUrl(path), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw await apiErrorFromResponse(resp);
  }
  return resp.json() as Promise<T>;
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(buildUrl(path), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw await apiErrorFromResponse(resp);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  // === Runs ===
  createRun: async (title?: string): Promise<ApiRun> => {
    return postJson<ApiRun>("/api/runs", { title });
  },
  listRuns: async (): Promise<ApiRun[]> => {
    return getJson<ApiRun[]>("/api/runs");
  },
  getRun: async (id: string): Promise<ApiRun> => {
    return getJson<ApiRun>(`/api/runs/${id}`);
  },
  getRunState: async (id: string): Promise<RunSession> => {
    const state = await getJson<RunSession>(`/api/runs/${id}/state`);
    return {
      ...state,
      approvals: state.approvals || state.pending_approvals || [],
      tasks: state.tasks || [],
    };
  },
  updateRun: async (
    id: string,
    patch: { title?: string; pinned?: boolean }
  ): Promise<ApiRun> => {
    return patchJson<ApiRun>(`/api/runs/${id}`, patch);
  },
  archiveRun: async (id: string): Promise<ApiRun> => {
    return postJson<ApiRun>(`/api/runs/${id}/archive`, {});
  },
  restoreRun: async (id: string): Promise<ApiRun> => {
    return postJson<ApiRun>(`/api/runs/${id}/restore`, {});
  },
  deleteRun: async (id: string): Promise<{ status: string }> => {
    return deleteJson(`/api/runs/${id}`);
  },
  cancelRun: async (id: string): Promise<{ status: string }> => {
    return postJson(`/api/runs/${id}/cancel`, {});
  },

  // === Messages ===
  sendMessage: async (
    runId: string,
    content: string,
    paperIds: string[] = [],
    publicId?: string,
    mode: "start" | "queue" | "interrupt" = "start",
  ): Promise<SendMessageResult> => {
    return postJson(`/api/runs/${runId}/messages`, {
      content,
      paper_ids: paperIds,
      public_id: publicId,
      mode,
    });
  },
  listMessages: async (runId: string): Promise<ApiMessage[]> => {
    return getJson<ApiMessage[]>(`/api/runs/${runId}/messages`);
  },

  // === Library ===
  listLibrary: async (): Promise<{ papers: ApiPaper[] }> => {
    return getJson(`/api/library`);
  },
  uploadPaper: async (file: File): Promise<ApiPaper> => {
    const formData = new FormData();
    formData.append("file", file);
    const resp = await fetch(buildUrl("/api/library/upload"), {
      method: "POST",
      body: formData,
    });
    if (!resp.ok) throw await apiErrorFromResponse(resp);
    return resp.json();
  },
  getPaper: async (paperId: string): Promise<{ paper: ApiPaper; capability_card: any }> => {
    return getJson(`/api/library/${paperId}`);
  },
  renamePaper: async (paperId: string, title: string): Promise<ApiPaper> => {
    return patchJson(`/api/library/${paperId}`, { title });
  },
  deletePaper: async (paperId: string): Promise<{ status: string }> => {
    return deleteJson(`/api/library/${paperId}`);
  },
  attachPaperToRun: async (runId: string, paperId: string): Promise<{ status: string }> => {
    return postJson(`/api/runs/${runId}/papers/${paperId}`, {});
  },
  detachPaperFromRun: async (runId: string, paperId: string): Promise<{ status: string }> => {
    return deleteJson(`/api/runs/${runId}/papers/${paperId}`);
  },
  downloadPaperPdf: async (paperId: string): Promise<Blob> => {
    const resp = await fetch(buildPaperPdfUrl(paperId));
    if (!resp.ok) throw await apiErrorFromResponse(resp);
    return resp.blob();
  },

  // === Sandboxes ===
  listSandboxes: async (): Promise<ApiSandbox[]> => {
    return getJson(`/api/sandboxes`);
  },
  getLatestSandboxForRun: async (runId: string): Promise<ApiSandbox | null> => {
    return getJson<ApiSandbox | null>(`/api/sandboxes/latest?run_id=${runId}`);
  },
  startSandbox: async (runId: string, appArtifactId: string): Promise<ApiSandbox> => {
    return postJson(`/api/sandboxes`, { app_artifact_id: appArtifactId, run_id: runId });
  },
  stopSandbox: async (sandboxId: string): Promise<{ status: string }> => {
    return postJson(`/api/sandboxes/${sandboxId}/stop`, {});
  },
  restartSandbox: async (sandboxId: string): Promise<ApiSandbox> => {
    return postJson(`/api/sandboxes/${sandboxId}/restart`, {});
  },
  getSandbox: async (sandboxId: string): Promise<ApiSandbox> => {
    return getJson<ApiSandbox>(`/api/sandboxes/${sandboxId}`);
  },
  listRunPapers: async (runId: string): Promise<{ papers: any[] }> => {
    return getJson(`/api/runs/${runId}/papers`);
  },
  readFile: async (sandboxId: string, path: string): Promise<{ path: string; content: string }> => {
    return getJson(`/api/files/sandboxes/${sandboxId}/files/${path}`);
  },
  writeFile: async (sandboxId: string, path: string, content: string): Promise<{ path: string; saved: boolean }> => {
    const resp = await fetch(buildUrl(`/api/files/sandboxes/${sandboxId}/files/${path}`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!resp.ok) throw await apiErrorFromResponse(resp);
    return resp.json();
  },
  getFileTree: async (sandboxId: string): Promise<{ tree: any[] }> => {
    return getJson(`/api/files/sandboxes/${sandboxId}/tree`);
  },
  createEntry: async (
    sandboxId: string,
    entry: { type: "file" | "directory"; path: string; content?: string }
  ): Promise<{ path: string; created: boolean }> => {
    return postJson(`/api/files/sandboxes/${sandboxId}/entries`, entry);
  },
  renameEntry: async (
    sandboxId: string,
    path: string,
    newPath: string
  ): Promise<{ path: string; renamed: boolean }> => {
    return patchJson(
      `/api/files/sandboxes/${sandboxId}/entries/${path}`,
      { new_path: newPath }
    );
  },
  deleteEntry: async (
    sandboxId: string,
    path: string
  ): Promise<{ path: string; deleted: boolean }> => {
    return deleteJson(`/api/files/sandboxes/${sandboxId}/entries/${path}`);
  },

  // === Preview ===
  getPreviewUrl: (sandboxId: string) => buildUrl(`/api/preview/${sandboxId}/`),

  // === Approvals ===
  resolveApproval: async (approvalId: string, approved: boolean): Promise<{ approval_id: string; approved: boolean }> => {
    return postJson(`/api/approvals/${approvalId}/resolve`, { approved });
  },
  listApprovals: async (runId?: string): Promise<ApiApproval[]> => {
    const q = runId ? `?run_id=${runId}` : "";
    return getJson(`/api/approvals${q}`);
  },

  // === Artifacts ===
  listArtifacts: async (runId: string, includeData = false): Promise<ApiArtifact[]> => {
    const params = new URLSearchParams({ run_id: runId });
    if (includeData) params.set("include_data", "true");
    return getJson(`/api/artifacts?${params.toString()}`);
  },
  getArtifact: async (artifactId: string): Promise<ApiArtifact> => {
    return getJson<ApiArtifact>(`/api/artifacts/${artifactId}`);
  },
  renameArtifact: async (artifactId: string, displayName: string): Promise<ApiArtifact> => {
    return patchJson<ApiArtifact>(`/api/artifacts/${artifactId}`, { display_name: displayName });
  },
  deleteArtifact: async (artifactId: string): Promise<{ status: string }> => {
    return deleteJson(`/api/artifacts/${artifactId}`);
  },
  downloadArtifact: async (artifactId: string): Promise<Blob> => {
    const resp = await fetch(buildUrl(`/api/artifacts/${artifactId}/download`));
    if (!resp.ok) throw await apiErrorFromResponse(resp);
    return resp.blob();
  },

  // === App-based file API ===
  listAppTree: async (appId: string, runId?: string): Promise<{ tree: any[] }> => {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return getJson(`/api/apps/${appId}/tree${query}`);
  },
  readAppFile: async (appId: string, path: string, runId?: string): Promise<{ path: string; content: string }> => {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return getJson(`/api/apps/${appId}/files/${path}${query}`);
  },
  writeAppFile: async (appId: string, path: string, content: string, runId?: string): Promise<{ path: string; saved: boolean }> => {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return putJson(`/api/apps/${appId}/files/${path}${query}`, { content });
  },
  createAppEntry: async (
    appId: string,
    entry: { type: "file" | "directory"; path: string; content?: string },
    runId?: string,
  ): Promise<{ path: string; created: boolean }> => {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return postJson(`/api/apps/${appId}/entries${query}`, entry);
  },
  renameAppEntry: async (
    appId: string,
    path: string,
    newPath: string,
    runId?: string,
  ): Promise<{ path: string; renamed: boolean }> => {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return patchJson(`/api/apps/${appId}/entries/${path}${query}`, { new_path: newPath });
  },
  deleteAppEntry: async (
    appId: string,
    path: string,
    runId?: string,
  ): Promise<{ path: string; deleted: boolean }> => {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return deleteJson(`/api/apps/${appId}/entries/${path}${query}`);
  },
  downloadAppZip: async (appId: string, runId?: string): Promise<Blob> => {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    const resp = await fetch(buildUrl(`/api/apps/${appId}/download${query}`));
    if (!resp.ok) throw await apiErrorFromResponse(resp);
    return resp.blob();
  },
  listAppRevisions: async (appId: string, runId?: string): Promise<{ revisions: any[] }> => {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return getJson(`/api/apps/${appId}/revisions${query}`);
  },
  getAppRevision: async (appId: string, revisionId: string, runId?: string): Promise<Record<string, unknown>> => {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return getJson(`/api/apps/${appId}/revisions/${revisionId}${query}`);
  },
  restoreAppRevision: async (appId: string, revisionId: string, runId?: string): Promise<{ restored: boolean; revision_id?: string }> => {    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return postJson(`/api/apps/${appId}/revisions/${revisionId}/restore${query}`, {});
  },

  getPreviewStatus: async (runId: string): Promise<Record<string, unknown>> => {
    return getJson(`/api/preview/status/${runId}`);
  },

  // === Tasks / Steps ===
  listRunTasks: async (runId: string): Promise<Task[]> => {
    return getJson<Task[]>(`/api/runs/${runId}/tasks`);
  },
  listTaskSteps: async (runId: string, taskId: string): Promise<any[]> => {
    return getJson<any[]>(`/api/runs/${runId}/tasks/${taskId}/steps`);
  },

  // === Settings ===
  getSettings: async (): Promise<Record<string, unknown>> => {
    return getJson(`/api/settings`);
  },
};

export interface RunEventBase<Type extends string, Payload = unknown> {
  version: 2;
  id: string;
  seq: number;
  run_id: string;
  task_id?: string | null;
  type: Type;
  ts: number | string;
  payload: Payload;
}

export interface MessageDeltaPayload {
  message_id: string;
  delta: string;
  text?: string;
}

export interface StepStartedPayload {
  step_id: string;
  task_id?: string;
  kind: string;
  title: string;
}

export interface StepProgressPayload {
  step_id: string;
  percent?: number;
  detail?: string;
}

export interface StepCompletedPayload {
  step_id: string;
  summary?: string;
}

export interface StepFailedPayload {
  step_id: string;
  error?: string;
}

export interface SandboxLogDeltaPayload {
  sandbox_id?: string;
  offset?: number;
  stream?: "stdout" | "stderr";
  text: string;
}

export interface SendMessageResult {
  status: string;
  run_id: string;
  message: {
    id: string;
    public_id?: string;
    task_id?: string;
    role?: string;
    content?: string;
    status?: string;
    created_at?: string;
  };
  task: ApiTask;
  task_id: string;
  event_cursor: number;
}

export interface TaskEventPayload {
  task: ApiTask;
}

export type KnownRunEvent =
  | RunEventBase<"message.delta", MessageDeltaPayload>
  | RunEventBase<"message.started", { message_id: string }>
  | RunEventBase<"message.completed", { message_id: string; content?: string }>
  | RunEventBase<"task.created", TaskEventPayload>
  | RunEventBase<"task.updated", TaskEventPayload>
  | RunEventBase<"task.completed", TaskEventPayload>
  | RunEventBase<"task.failed", TaskEventPayload>
  | RunEventBase<"task.cancelled", TaskEventPayload>
  | RunEventBase<"step.started", StepStartedPayload>
  | RunEventBase<"step.progress", StepProgressPayload>
  | RunEventBase<"step.completed", StepCompletedPayload>
  | RunEventBase<"step.failed", StepFailedPayload>
  | RunEventBase<"sandbox.log.delta", SandboxLogDeltaPayload>
  | RunEventBase<string>;

export type RunEvent = KnownRunEvent;

export type ConnectionState = "connecting" | "connected" | "error";

export class SSEClient {
  private es: EventSource | null = null;
  private handler: ((event: RunEvent) => void) | null = null;
  private stateHandler: ((state: ConnectionState) => void) | null = null;
  private seenSeqs = new Set<number>();

  connect(runId: string, afterSeq = 0) {
    this.disconnect();
    this.seenSeqs.clear();
    this.setState("connecting");
    const query = afterSeq > 0 ? `?after_seq=${afterSeq}` : "";
    this.es = new EventSource(buildUrl(`/api/runs/${runId}/events${query}`));

    this.es.onopen = () => {
      this.setState("connected");
    };

    this.es.onerror = () => {
      // onerror fires both on transient failures (browser auto-reconnects)
      // and on the terminal closed state. EventSource has no clean
      // "disconnected" signal, so we report error and let the next onopen
      // flip it back to connected.
      this.setState("error");
    };

    // Single onmessage: the semantic type lives in the JSON envelope, so we
    // no longer need named `event:` blocks or per-type subscriptions.
    this.es.onmessage = (e: MessageEvent) => {
      try {
        const event = JSON.parse(e.data) as RunEvent;
        if (this.seenSeqs.has(event.seq)) {
          return; // dedup
        }
        this.seenSeqs.add(event.seq);
        // Cap memory: keep last 500 seqs.
        if (this.seenSeqs.size > 500) {
          const arr = Array.from(this.seenSeqs).sort((a, b) => a - b);
          for (let i = 0; i < 250; i++) this.seenSeqs.delete(arr[i]);
        }
        this.handler?.(event);
      } catch (err) {
        console.error("[SSE] parse error:", err);
      }
    };
  }

  onMessage(handler: (event: RunEvent) => void) {
    this.handler = handler;
  }

  onConnectionState(handler: (state: ConnectionState) => void) {
    this.stateHandler = handler;
  }

  private setState(state: ConnectionState) {
    try {
      this.stateHandler?.(state);
    } catch (err) {
      console.error("[SSE] state handler error:", err);
    }
  }

  disconnect() {
    if (this.es) {
      this.es.close();
      this.es = null;
    }
  }
}
