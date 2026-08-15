"use client";

import type { ReactNode } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { useAppStore } from "@/lib/store";

// Persisted conversation/workbench split, keyed by run-wide layout. Stored in
// a module-level map so it survives unmount; persisted to sessionStorage so it
// survives refresh (doc 6.3).
type Layout = { conversation: number; workbench: number };
const LAYOUT_KEY = "paperforge-workspace-layout";
let committed: Layout | null = null;
try {
  const raw = window.sessionStorage.getItem(LAYOUT_KEY);
  if (raw) committed = JSON.parse(raw) as Layout;
} catch {
  /* ignore malformed stored layout */
}

function persist(layout: Layout) {
  committed = layout;
  try {
    window.sessionStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
  } catch {
    /* ignore quota errors */
  }
}

interface AppShellProps {
  sidebar: ReactNode;
  conversation: ReactNode;
  workbench: ReactNode;
}

export function AppShell({ sidebar, conversation, workbench }: AppShellProps) {
  const workbenchMode = useAppStore((s) => s.workbenchMode);

  if (workbenchMode === "closed") {
    return (
      <div className="flex h-dvh min-h-0 overflow-hidden">
        {sidebar}
        <main className="flex min-w-0 flex-1 overflow-hidden">{conversation}</main>
      </div>
    );
  }

  return (
    <div className="flex h-dvh min-h-0 overflow-hidden">
      {sidebar}
      <PanelGroup
        direction="horizontal"
        className="min-w-0 flex-1"
        autoSaveId="paperforge-workspace"
      >
        <Panel
          defaultSize={committed?.conversation ?? 54}
          minSize={34}
          className="min-w-0"
        >
          <div className="h-full min-h-0 overflow-hidden">{conversation}</div>
        </Panel>
        <PanelResizeHandle className="w-1 bg-border hover:bg-primary/40 transition-colors" />
        <Panel
          defaultSize={committed?.workbench ?? 46}
          minSize={28}
          maxSize={66}
          className="min-w-0"
        >
          <div className="h-full min-h-0 overflow-hidden">{workbench}</div>
        </Panel>
      </PanelGroup>
    </div>
  );
}

export { persist, LAYOUT_KEY };
