"use client";

import { useAppStore } from "@/lib/store";
import { PreviewPanel } from "../PreviewPanel";

export function WorkbenchPane() {
  const setWorkbenchMode = useAppStore((s) => s.setWorkbenchMode);
  const setWorkbenchPinnedClosed = useAppStore((s) => s.setWorkbenchPinnedClosed);

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden">
      <button
        onClick={() => {
          setWorkbenchPinnedClosed(true);
          setWorkbenchMode("closed");
        }}
        className="absolute right-2 top-2 z-10 px-2 py-1 text-xs text-muted-foreground hover:text-foreground rounded border border-border bg-background/80"
        aria-label="Close workbench"
      >
        ››
      </button>
      <PreviewPanel />
    </div>
  );
}
