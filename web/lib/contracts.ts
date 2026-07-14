import type {
  Approval,
  Artifact,
  Event,
  Message,
  Run,
  Sandbox,
} from "./store";

export interface Task {
  id: string;
  task_id?: string;
  run_id?: string;
  title?: string | null;
  goal?: string | null;
  status: string;
  phase?: string;
  created_at?: string;
  updated_at?: string;
  completed_at?: string | null;
}

export interface PreviewState {
  status: "idle" | "starting" | "running" | "degraded" | "stopped" | "error";
  sandbox_id?: string | null;
  preview_url?: string | null;
  error?: string | null;
}

export interface RunSession {
  run: Run;
  messages: Message[];
  artifacts: Artifact[];
  sandbox: Sandbox | null;
  pending_approvals: Approval[];
  approvals: Approval[];
  tasks: Task[];
  event_cursor: number;
  preview?: PreviewState | null;
}

export interface RunEventEnvelope<T = unknown> {
  id: string;
  seq: number;
  run_id: string;
  type: string;
  ts: number | string;
  payload: T;
}

export type SessionEvent = Event & {
  seq: number;
  run_id: string;
};
