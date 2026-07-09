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
  deleteRun: async (id: string): Promise<{ status: string }> => {
    return deleteJson(`/api/runs/${id}`);
  },

  // === Messages ===
  sendMessage: async (runId: string, content: string): Promise<{ status: string; run_id: string }> => {
    return postJson(`/api/runs/${runId}/messages`, { content });
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
  getSandbox: async (sandboxId: string): Promise<Sandbox> => {
    return getJson<Sandbox>(`/api/sandboxes/${sandboxId}`);
  },

  // === Files ===
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
    return getJson(`/api/artifacts/${artifactId}`);
  },

  // === Settings ===
  getSettings: async (): Promise<any> => {
    return getJson(`/api/settings`);
  },
};

// === SSE Client ===

export class SSEClient {
  private es: EventSource | null = null;
  private handlers: Record<string, (data: any) => void> = {};

  connect(runId: string) {
    this.disconnect();
    this.es = new EventSource(buildUrl(`/api/runs/${runId}/events`));

    this.es.onopen = () => {
      console.log("SSE connected");
    };

    this.es.onerror = (e) => {
      console.warn("SSE error, attempting reconnect in 1s...");
      setTimeout(() => {
        if (this.es) this.connect(runId);
      }, 1000);
    };

    // Listen for typed events
    for (const type of Object.keys(this.handlers)) {
      this._attach(type, this.handlers[type]);
    }
  }

  on(eventType: string, handler: (data: any) => void) {
    this.handlers[eventType] = handler;
    if (this.es) {
      this._attach(eventType, handler);
    }
  }

  private _attach(eventType: string, handler: (data: any) => void) {
    if (!this.es) return;
    this.es.addEventListener(eventType, (e: any) => {
      try {
        const data = JSON.parse(e.data);
        handler(data);
      } catch (err) {
        console.error("SSE parse error:", err);
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
