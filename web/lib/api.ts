import type { Run, Message, Paper, Sandbox, Event, Approval, Artifact } from "./store";
import type { RunSession } from "./contracts";

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

async function postJson<T>(path: string, body?: any): Promise<T> {
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

async function patchJson<T>(path: string, body: any): Promise<T> {
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

async function putJson<T>(path: string, body: any): Promise<T> {
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
  createRun: async (title?: string): Promise<Run> => {
    return postJson<Run>("/api/runs", { title });
  },
  listRuns: async (): Promise<Run[]> => {
    return getJson<Run[]>("/api/runs");
  },
  getRun: async (id: string): Promise<Run> => {
    return getJson<Run>(`/api/runs/${id}`);
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
  ): Promise<Run> => {
    return patchJson<Run>(`/api/runs/${id}`, patch);
  },
  archiveRun: async (id: string): Promise<Run> => {
    return postJson<Run>(`/api/runs/${id}/archive`, {});
  },
  restoreRun: async (id: string): Promise<Run> => {
    return postJson<Run>(`/api/runs/${id}/restore`, {});
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
  ): Promise<{ status: string; run_id: string; message?: any }> => {
    return postJson(`/api/runs/${runId}/messages`, {
      content,
      paper_ids: paperIds,
      public_id: publicId,
    });
  },
  listMessages: async (runId: string): Promise<Message[]> => {
    return getJson<Message[]>(`/api/runs/${runId}/messages`);
  },

  // === Library ===
  listLibrary: async (): Promise<{ papers: Paper[] }> => {
    return getJson(`/api/library`);
  },
  uploadPaper: async (file: File): Promise<Paper> => {
    const formData = new FormData();
    formData.append("file", file);
    const resp = await fetch(buildUrl("/api/library/upload"), {
      method: "POST",
      body: formData,
    });
    if (!resp.ok) throw await apiErrorFromResponse(resp);
    return resp.json();
  },
  getPaper: async (paperId: string): Promise<{ paper: Paper; capability_card: any }> => {
    return getJson(`/api/library/${paperId}`);
  },
  renamePaper: async (paperId: string, title: string): Promise<Paper> => {
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
  listSandboxes: async (): Promise<Sandbox[]> => {
    return getJson(`/api/sandboxes`);
  },
  getLatestSandboxForRun: async (runId: string): Promise<Sandbox | null> => {
    return getJson<Sandbox | null>(`/api/sandboxes/latest?run_id=${runId}`);
  },
  startSandbox: async (runId: string, appArtifactId: string): Promise<Sandbox> => {
    return postJson(`/api/sandboxes`, { app_artifact_id: appArtifactId, run_id: runId });
  },
  stopSandbox: async (sandboxId: string): Promise<{ status: string }> => {
    return postJson(`/api/sandboxes/${sandboxId}/stop`, {});
  },
  restartSandbox: async (sandboxId: string): Promise<Sandbox> => {
    return postJson(`/api/sandboxes/${sandboxId}/restart`, {});
  },
  getSandbox: async (sandboxId: string): Promise<Sandbox> => {
    return getJson<Sandbox>(`/api/sandboxes/${sandboxId}`);
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
  listApprovals: async (runId?: string): Promise<Approval[]> => {
    const q = runId ? `?run_id=${runId}` : "";
    return getJson(`/api/approvals${q}`);
  },

  // === Artifacts ===
  listArtifacts: async (runId: string, includeData = false): Promise<Artifact[]> => {
    const params = new URLSearchParams({ run_id: runId });
    if (includeData) params.set("include_data", "true");
    return getJson(`/api/artifacts?${params.toString()}`);
  },
  getArtifact: async (artifactId: string): Promise<Artifact> => {
    return getJson<Artifact>(`/api/artifacts/${artifactId}`);
  },
  renameArtifact: async (artifactId: string, displayName: string): Promise<Artifact> => {
    return patchJson<Artifact>(`/api/artifacts/${artifactId}`, { display_name: displayName });
  },
  deleteArtifact: async (artifactId: string): Promise<{ status: string }> => {
    return deleteJson(`/api/artifacts/${artifactId}`);
  },
  downloadArtifact: async (artifactId: string): Promise<Blob> => {
    const resp = await fetch(buildUrl(`/api/artifacts/${artifactId}/download`));
    if (!resp.ok) throw await apiErrorFromResponse(resp);
    return resp.blob();
  },

  // === App-based file API (doc 8.4) ===
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
  getAppRevision: async (appId: string, revisionId: string, runId?: string): Promise<any> => {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return getJson(`/api/apps/${appId}/revisions/${revisionId}${query}`);
  },
  restoreAppRevision: async (appId: string, revisionId: string, runId?: string): Promise<{ restored: boolean; revision_id?: string }> => {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return postJson(`/api/apps/${appId}/revisions/${revisionId}/restore${query}`, {});
  },

  getPreviewStatus: async (runId: string): Promise<any> => {
    return getJson(`/api/preview/status/${runId}`);
  },

  // === Settings ===
  getSettings: async (): Promise<any> => {
    return getJson(`/api/settings`);
  },
};

export interface RunEvent<T = unknown> {
  id: string;
  seq: number;
  run_id: string;
  type: string;
  ts: number | string;
  payload: T;
}

export class SSEClient {
  private es: EventSource | null = null;
  private handlers: Record<string, (payload: any, event: RunEvent) => void> = {};
  private seenSeqs = new Set<number>();

  connect(runId: string, afterSeq = 0) {
    this.disconnect();
    this.seenSeqs.clear();
    const query = afterSeq > 0 ? `?after_seq=${afterSeq}` : "";
    this.es = new EventSource(buildUrl(`/api/runs/${runId}/events${query}`));

    this.es.onopen = () => {
      console.log("[SSE] connected");
    };

    this.es.onerror = () => {
      console.warn("[SSE] error; browser will auto-reconnect");
    };

    // Re-attach all previously-registered handlers to the new EventSource.
    for (const type of Object.keys(this.handlers)) {
      this._attach(type, this.handlers[type]);
    }
  }

  on<T = any>(eventType: string, handler: (payload: T, event: RunEvent<T>) => void) {
    this.handlers[eventType] = handler as any;
    if (this.es) {
      this._attach(eventType, handler as any);
    }
  }

  private _attach(eventType: string, handler: (payload: any, event: RunEvent) => void) {
    if (!this.es) return;
    this.es.addEventListener(eventType, (e: MessageEvent) => {
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
        handler(event.payload, event);
      } catch (err) {
        console.error("[SSE] parse error:", err);
      }
    });
  }

  disconnect() {
    if (this.es) {
      this.es.close();
      this.es = null;
    }
  }
}
