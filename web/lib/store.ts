"use client";

import { create } from "zustand";

export interface Message {
  id?: string;
  run_id?: string;
  role: "user" | "assistant" | "tool";
  content: string;
  tool_calls?: any[];
  tool_call_id?: string;
  name?: string;
  created_at?: string;
}

export interface Run {
  id: string;
  title: string;
  status: string;
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
}

export interface Sandbox {
  id: string;
  run_id?: string;
  container_id?: string;
  app_path?: string;
  preview_port?: number;
  status: string;
  started_at?: string;
  stopped_at?: string;
}

export interface Event {
  id: string;
  type: string;
  data: any;
  run_id: string;
  ts?: number;
}

export interface Approval {
  approval_id: string;
  tool: string;
  args: Record<string, any>;
  status: "pending" | "approved" | "rejected";
}

interface AppState {
  currentRun: Run | null;
  messages: Message[];
  events: Event[];
  sandbox: Sandbox | null;
  pendingApprovals: Approval[];
  activeTab: "preview" | "code" | "console" | "verification";
  sidebarCollapsed: boolean;

  setCurrentRun: (run: Run | null) => void;
  addMessage: (msg: Message) => void;
  addEvent: (event: Event) => void;
  setSandbox: (sb: Sandbox | null) => void;
  addPendingApproval: (approval: Approval) => void;
  resolvePendingApproval: (approvalId: string, approved: boolean) => void;
  setActiveTab: (tab: "preview" | "code" | "console" | "verification") => void;
  toggleSidebar: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  currentRun: null,
  messages: [],
  events: [],
  sandbox: null,
  pendingApprovals: [],
  activeTab: "preview",
  sidebarCollapsed: false,

  setCurrentRun: (run) =>
    set({ currentRun: run, messages: [], events: [], pendingApprovals: [] }),
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  addEvent: (event) => set((s) => ({ events: [...s.events, event] })),
  setSandbox: (sb) => set({ sandbox: sb }),
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
  setActiveTab: (tab) => set({ activeTab: tab }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
}));
