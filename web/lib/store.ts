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

interface AppState {
  // Current run
  currentRun: Run | null;
  messages: Message[];
  events: Event[];

  // Sandbox
  sandbox: Sandbox | null;

  // UI
  activeTab: "preview" | "code" | "console" | "verification";
  sidebarCollapsed: boolean;

  // Actions
  setCurrentRun: (run: Run | null) => void;
  addMessage: (msg: Message) => void;
  addEvent: (event: Event) => void;
  setSandbox: (sb: Sandbox | null) => void;
  setActiveTab: (tab: "preview" | "code" | "console" | "verification") => void;
  toggleSidebar: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  currentRun: null,
  messages: [],
  events: [],
  sandbox: null,
  activeTab: "preview",
  sidebarCollapsed: false,

  setCurrentRun: (run) =>
    set({ currentRun: run, messages: [], events: [] }),
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  addEvent: (event) => set((s) => ({ events: [...s.events, event] })),
  setSandbox: (sb) => set({ sandbox: sb }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
}));
