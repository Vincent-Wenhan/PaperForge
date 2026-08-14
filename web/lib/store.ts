"use client";

import { create } from "zustand";
import type { ConnectionState } from "./api";
import type { PreviewState, Task } from "./contracts";

export interface Message {
  id?: string;
  public_id?: string;
  run_id?: string;
  task_id?: string;
  role: "user" | "assistant" | "tool";
  content: string;
  tool_calls?: any[];
  tool_call_id?: string;
  name?: string;
  created_at?: string;
  streaming?: boolean;
  status?: "streaming" | "completed" | "failed";
}

export interface Run {
  id: string;
  title: string;
  status: string;
  preview_status?: "idle" | "starting" | "running" | "degraded" | "stopped" | "error";
  phase?: string;
  pinned?: boolean;
  archived_at?: string | null;
  last_message_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Paper {
  paper_id: string;
  title: string;
  pdf_path: string;
  status: string;
  created_at?: string;
  parsed_at?: string;
  card_path?: string;
}

export interface Sandbox {
  id: string;
  run_id?: string;
  container_id?: string;
  app_path?: string;
  preview_port?: number;
  status: string;
  environment?: string;
  preview_url?: string | null;
  error?: string | null;
  started_at?: string;
  stopped_at?: string;
}

export interface Event {
  id: string;
  type: string;
  data: any;
  run_id: string;
  ts?: number | string;
  seq?: number;
}

export interface Approval {
  approval_id: string;
  id?: string;
  run_id?: string;
  task_id?: string;
  tool: string;
  tool_name?: string;
  args: Record<string, any>;
  status: "pending" | "approved" | "rejected" | "expired";
  created_at?: string;
  resolved_at?: string | null;
}

export interface Artifact {
  id: string;
  run_id?: string;
  task_id?: string;
  type: string;
  path?: string;
  metadata?: Record<string, any>;
  data?: any;
  created_at?: string;
}

export interface AgentStep {
  id: string;
  task_id?: string;
  kind?: string;
  title?: string;
  status: "pending" | "running" | "completed" | "failed";
  detail?: string;
  summary?: string;
  percent?: number;
}

export interface SandboxLog {
  sandbox_id?: string;
  offset: number;
  stream: "stdout" | "stderr";
  text: string;
}

export interface Attachment {
  id: string;
  type: "file" | "paper";
  name: string;
  file?: File;
  paperId?: string;
}

interface AppState {
  currentRun: Run | null;
  messages: Message[];
  events: Event[];
  steps: AgentStep[];
  sandboxLogs: SandboxLog[];
  sandbox: Sandbox | null;
  tasks: Task[];
  preview: PreviewState | null;
  sessionError: string | null;
  pendingApprovals: Approval[];
  artifacts: Artifact[];
  attachments: Attachment[];
  isRunning: boolean;
  activeTab: "preview" | "files" | "artifacts" | "console" | "verification";
  sidebarCollapsed: boolean;
  workbenchMode: "closed" | "peek" | "open";
  workbenchPinnedClosed: boolean;
  lastSeq: number;
  composerPrefill: string;
  connection: ConnectionState;

  setCurrentRun: (run: Run | null) => void;
  updateCurrentRun: (patch: Partial<Run>) => void;
  setWorkbenchMode: (mode: "closed" | "peek" | "open") => void;
  setWorkbenchPinnedClosed: (pinned: boolean) => void;
  setSandbox: (sb: Sandbox | null) => void;
  setTasks: (tasks: Task[]) => void;
  upsertTask: (task: Task) => void;
  setPreview: (preview: PreviewState | null) => void;
  setSessionError: (error: string | null) => void;
  setPendingApprovals: (approvals: Approval[]) => void;
  addMessage: (msg: Message) => void;
  upsertMessage: (msg: Message) => void;
  appendAssistantDelta: (text: string) => void;
  appendMessageDelta: (messageId: string, delta: string, taskId?: string) => void;
  completeMessage: (messageId: string, content: string) => void;
  failMessage: (messageId: string, error: string) => void;
  finalizeStreamingAssistant: () => void;
  replaceMessages: (msgs: Message[]) => void;
  removeMessage: (messageId: string) => void;
  addEvent: (event: Event) => void;
  upsertStep: (step: AgentStep) => void;
  setSteps: (steps: AgentStep[]) => void;
  appendSandboxLog: (log: SandboxLog) => void;
  clearSandboxLogs: () => void;
  addPendingApproval: (approval: Approval) => void;
  resolvePendingApproval: (approvalId: string, approved: boolean) => void;
  setArtifacts: (artifacts: Artifact[]) => void;
  addArtifact: (artifact: Artifact) => void;
  updateArtifact: (artifact: Partial<Artifact> & Pick<Artifact, "id">) => void;
  updateRunStatus: (status: string) => void;
  setActiveTab: (tab: "preview" | "files" | "artifacts" | "console" | "verification") => void;
  toggleSidebar: () => void;
  setIsRunning: (running: boolean) => void;
  addAttachment: (attachment: Attachment) => void;
  removeAttachment: (id: string) => void;
  clearAttachments: () => void;
  setLastSeq: (seq: number) => void;
  setComposerPrefill: (text: string) => void;
  setConnection: (state: ConnectionState) => void;
  reconcileMessage: (patch: Partial<Message> & Pick<Message, "id">) => void;
  removeMessageById: (id: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  currentRun: null,
  messages: [],
  events: [],
  steps: [],
  sandboxLogs: [],
  sandbox: null,
  tasks: [],
  preview: null,
  sessionError: null,
  pendingApprovals: [],
  artifacts: [],
  attachments: [],
  isRunning: false,
  activeTab: "preview",
  sidebarCollapsed: false,
  workbenchMode: "closed",
  workbenchPinnedClosed: false,
  lastSeq: 0,
  composerPrefill: "",
  connection: "connecting",

  setCurrentRun: (run) =>
    set({
      currentRun: run,
      messages: [],
      events: [],
      steps: [],
      pendingApprovals: [],
      artifacts: [],
      sandbox: null,
      tasks: [],
      preview: null,
      attachments: [],
      isRunning: false,
      lastSeq: 0,
      sessionError: null,
    }),
  updateCurrentRun: (patch) =>
    set((s) =>
      s.currentRun ? { currentRun: { ...s.currentRun, ...patch } } : {},
    ),
  setWorkbenchMode: (mode) => set({ workbenchMode: mode }),
  setWorkbenchPinnedClosed: (pinned) => set({ workbenchPinnedClosed: pinned }),
  setSandbox: (sb) => set({ sandbox: sb }),
  setTasks: (tasks) => set({ tasks }),
  upsertTask: (task) =>
    set((s) => {
      const index = s.tasks.findIndex((item) => item.id === task.id);
      if (index < 0) return { tasks: [...s.tasks, task] };
      const tasks = [...s.tasks];
      tasks[index] = { ...tasks[index], ...task };
      return { tasks };
    }),
  setPreview: (preview) => set({ preview }),
  setSessionError: (error) => set({ sessionError: error }),
  setPendingApprovals: (approvals) => set({ pendingApprovals: approvals }),
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  upsertMessage: (msg) =>
    set((s) => {
      const idx = s.messages.findIndex((m) =>
        m.id === msg.id || (msg.public_id && m.public_id === msg.public_id),
      );
      if (idx >= 0) {
        const copy = [...s.messages];
        copy[idx] = { ...copy[idx], ...msg };
        return { messages: copy };
      }
      return { messages: [...s.messages, msg] };
    }),
  appendAssistantDelta: (text) =>    set((s) => {
      const last = s.messages[s.messages.length - 1];
      if (last && last.role === "assistant" && last.streaming) {
        const updated = { ...last, content: last.content + text };
        return { messages: [...s.messages.slice(0, -1), updated] };
      }
      return {
        messages: [
          ...s.messages,
          { role: "assistant", content: text, streaming: true } as Message,
        ],
      };
    }),
  appendMessageDelta: (messageId, delta, taskId) =>
    set((s) => {
      const idx = s.messages.findIndex((m) => m.id === messageId);
      if (idx < 0) {
        // Message not yet known — create a placeholder streaming message.
        return {
          messages: [
            ...s.messages,
            {
              id: messageId,
              run_id: s.currentRun?.id,
              task_id: taskId,
              role: "assistant",
              content: delta,
              streaming: true,
              status: "streaming",
            } as Message,
          ],
        };
      }
      const copy = [...s.messages];
      const existing = copy[idx];
      const nextContent = (existing.content || "") + delta;
      copy[idx] = {
        ...existing,
        content: nextContent,
        streaming: true,
        status: "streaming",
      };
      return { messages: copy };
    }),
  completeMessage: (messageId, content) =>
    set((s) => {
      const idx = s.messages.findIndex((m) => m.id === messageId);
      if (idx < 0) {
        return {
          messages: [
            ...s.messages,
            {
              id: messageId,
              role: "assistant",
              content,
              streaming: false,
              status: "completed",
            } as Message,
          ],
        };
      }
      const copy = [...s.messages];
      copy[idx] = {
        ...copy[idx],
        content,
        streaming: false,
        status: "completed",
      };
      return { messages: copy };
    }),
  failMessage: (messageId, error) =>
    set((s) => {
      const idx = s.messages.findIndex((m) => m.id === messageId);
      if (idx < 0) return {};
      const copy = [...s.messages];
      copy[idx] = {
        ...copy[idx],
        streaming: false,
        status: "failed",
        content: error,
      };
      return { messages: copy };
    }),
  finalizeStreamingAssistant: () =>
    set((s) => {
      const last = s.messages[s.messages.length - 1];
      if (last && last.role === "assistant" && last.streaming) {
        const updated = { ...last, streaming: false, status: "completed" as const };
        return { messages: [...s.messages.slice(0, -1), updated] };
      }
      return {};
    }),
  replaceMessages: (msgs) => set({ messages: msgs }),
  removeMessage: (messageId) =>
    set((s) => ({ messages: s.messages.filter((m) => m.id !== messageId) })),
  // Debug event ring buffer capped at 500 to bound memory; the debug drawer
  // only needs the tail. Raise MAX_DEBUG_EVENTS if it ever helps.
  addEvent: (event) =>
    set((s) => {
      const events = [...s.events, event];
      return {
        events: events.length > 500 ? events.slice(-500) : events,
      };
    }),
  upsertStep: (step) =>
    set((s) => {
      const idx = s.steps.findIndex((item) => item.id === step.id);
      if (idx < 0) return { steps: [...s.steps, step] };
      const steps = [...s.steps];
      steps[idx] = { ...steps[idx], ...step };
      return { steps };
    }),
  setSteps: (steps) => set({ steps }),
  // Cap accumulated sandbox log deltas so memory stays bounded; superseded by
  // full docker logs in production.
  appendSandboxLog: (log) =>
    set((s) => {
      const logs = [...s.sandboxLogs, log];
      return { sandboxLogs: logs.length > 2000 ? logs.slice(-2000) : logs };
    }),
  clearSandboxLogs: () => set({ sandboxLogs: [] }),
  addPendingApproval: (approval) =>
    set((s) =>
      s.pendingApprovals.some((a) => a.approval_id === approval.approval_id)
        ? s
        : { pendingApprovals: [...s.pendingApprovals, approval] }
    ),
  resolvePendingApproval: (approvalId, approved) =>
    set((s) => ({
      pendingApprovals: s.pendingApprovals.map((a) =>
        a.approval_id === approvalId
          ? { ...a, status: approved ? "approved" : "rejected" }
          : a
      ),
    })),
  setArtifacts: (artifacts) => set({ artifacts }),
  addArtifact: (artifact) =>
    set((s) =>
      s.artifacts.some((a) => a.id === artifact.id)
        ? s
        : { artifacts: [...s.artifacts, artifact] }
    ),
  updateArtifact: (artifact) =>
    set((s) => ({
      artifacts: s.artifacts.map((item) =>
        item.id === artifact.id ? { ...item, ...artifact } : item,
      ),
    })),
  updateRunStatus: (status) =>
    set((s) => (s.currentRun ? { currentRun: { ...s.currentRun, status } } : {})),
  setActiveTab: (tab) => set({ activeTab: tab }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setIsRunning: (running) => set({ isRunning: running }),
  addAttachment: (attachment) =>
    set((s) => ({ attachments: [...s.attachments, attachment] })),
  removeAttachment: (id) =>
    set((s) => ({ attachments: s.attachments.filter((a) => a.id !== id) })),
  clearAttachments: () => set({ attachments: [] }),
  setLastSeq: (seq) => set((s) => ({ lastSeq: Math.max(s.lastSeq, seq) })),
  setComposerPrefill: (text) => set({ composerPrefill: text }),
  setConnection: (state) => set({ connection: state }),
  reconcileMessage: (patch) =>
    set((s) => {
      // Reconcile an optimistic message with the server's authoritative row.
      // Match on either the optimistic id or the public_id server returned.
      const idx = s.messages.findIndex(
        (m) =>
          m.id === patch.id ||
          m.public_id === patch.id ||
          m.id === patch.public_id,
      );
      if (idx < 0) return s;
      const copy = [...s.messages];
      copy[idx] = {
        ...copy[idx],
        ...patch,
        // The optimistic id is synthesized; the authoritative id wins.
        id: patch.id || copy[idx].id,
        public_id: patch.public_id || patch.id || copy[idx].public_id,
      };
      return { messages: copy };
    }),
  removeMessageById: (id) =>
    set((s) => ({
      messages: s.messages.filter(
        (m) => m.id !== id && m.public_id !== id,
      ),
    })),
}));
