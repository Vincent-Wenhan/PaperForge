import type { Run, Message, Paper, Sandbox, Event, Approval, Artifact } from "./store";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

function buildUrl(path: string): string {
  if (API_BASE) return `${API_BASE}${path}`;
  return path;
}

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(buildUrl(path));
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
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
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
  return resp.json() as Promise<T>;
}

async function deleteJson<T>(path: string): Promise<T> {
  const resp = await fetch(buildUrl(path), { method: "DELETE" });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
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
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
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
  getRunState: async (id: string): Promise<{
    run: Run;
    messages: Message[];
    artifacts: Artifact[];
    sandbox: Sandbox | null;
    pending_approvals: Approval[];
    event_cursor: number;
  }> => {
    return getJson(`/api/runs/${id}/state`);
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
  ): Promise<{ status: string; run_id: string }> => {
    return postJson(`/api/runs/${runId}/messages`, {
      content,
      paper_ids: paperIds,
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
    if (!resp.ok) throw new Error("Upload failed");
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

  // === Sandboxes ===
  listSandboxes: async (): Promise<Sandbox[]> => {
    return getJson(`/api/sandboxes`);
  },
  startSandbox: async (runId: string, appPath: string): Promise<Sandbox> => {
    return postJson(`/api/sandboxes`, { app_path: appPath, run_id: runId });
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
  readFile: async (sandboxId: string, path: string): Promise<{ path: string; content: string }> => {
    return getJson(`/api/files/sandboxes/${sandboxId}/files/${path}`);
  },
  writeFile: async (sandboxId: string, path: string, content: string): Promise<{ path: string; saved: boolean }> => {
    const resp = await fetch(buildUrl(`/api/files/sandboxes/${sandboxId}/files/${path}`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!resp.ok) throw new Error("Write failed");
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
    if (!resp.ok) throw new Error("Download failed");
    return resp.blob();
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
  ts: number;
  payload: T;
}

export class SSEClient {
  private es: EventSource | null = null;
  private handlers: Record<string, (payload: any, event: RunEvent) => void> = {};
  private seenSeqs = new Set<number>();

  connect(runId: string) {
    this.disconnect();
    this.es = new EventSource(buildUrl(`/api/runs/${runId}/events`));

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
