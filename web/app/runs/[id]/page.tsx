"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { useRunSession } from "@/lib/useRunSession";
import { Sidebar } from "@/components/Sidebar";
import { GlobalHeader } from "@/components/shell/GlobalHeader";
import { AppShell } from "@/components/shell/AppShell";
import { ConversationPane } from "@/components/shell/ConversationPane";
import { WorkbenchPane } from "@/components/shell/WorkbenchPane";
import { CommandPalette } from "@/components/dialogs/CommandPalette";
import { SkeletonMessage, SidebarSkeleton } from "@/components/Skeleton";

export default function RunWorkspacePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [runs, setRuns] = useState<any[]>([]);
  const [library, setLibrary] = useState<any[]>([]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const session = useRunSession(params.id);
  const currentRun = useAppStore((s) => s.currentRun);
  const currentRunId = useAppStore((s) => s.currentRun?.id);
  const workbenchMode = useAppStore((s) => s.workbenchMode);
  const connection = useAppStore((s) => s.connection);
  const isRunning = useAppStore((s) => s.isRunning);

  useEffect(() => {
    Promise.all([api.listRuns(), api.listLibrary()])
      .then(([runsResp, libResp]) => {
        setRuns(runsResp);
        setLibrary(libResp.papers || []);
      })
      .catch(console.error);
  }, []);

  const loading = session.loading;
  const error = session.error?.userMessage || null;

  useEffect(() => {
    if (!currentRun) return;
    setRuns((prev) => {
      const index = prev.findIndex((run) => run.id === currentRun.id);
      if (index < 0) return [currentRun, ...prev];
      const next = [...prev];
      next[index] = { ...next[index], ...currentRun };
      return next;
    });
  }, [currentRun]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, []);

  useEffect(() => {
    if (isRunning) setMobileSidebarOpen(false);
  }, [isRunning]);

  const handleNewRun = async () => {
    const run = await api.createRun("New Run");
    setRuns((prev) => [run, ...prev]);
    router.push(`/runs/${run.id}`);
  };

  const handleSelectRun = (runId: string) => {
    router.push(`/runs/${runId}`);
    setMobileSidebarOpen(false);
  };

  const attachPaper = (paper: any) => {
    const store = useAppStore.getState();
    store.addAttachment({
      id: `paper-${paper.paper_id}`,
      type: "paper",
      name: paper.title,
      paperId: paper.paper_id,
    });
  };

  const sidebar = (
    <Sidebar
      runs={runs}
      library={library}
      onNewRun={handleNewRun}
      onSelectRun={handleSelectRun}
      currentRunId={currentRunId}
      collapsed={sidebarCollapsed}
      onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
      onCloseMobile={() => setMobileSidebarOpen(false)}
      onOpenPaper={(paperId) => router.push(`/library/${paperId}`)}
      onAttachPaper={attachPaper}
    />
  );

  if (loading) {
    return (
      <>
        <div className="flex h-dvh min-h-0 flex-col overflow-hidden">
          <GlobalHeader
            onToggleCommandPalette={() => setPaletteOpen(true)}
            currentRun={currentRun}
            connectionStatus={session.error ? "error" : connection}
          />
          <div className="flex flex-1 min-h-0 overflow-hidden">
            <SidebarSkeleton />
            <div className="flex-1 p-4 space-y-4">
              <SkeletonMessage />
              <SkeletonMessage />
            </div>
          </div>
        </div>
        {error && (
          <div className="flex items-center justify-between gap-3 border-b border-destructive/30 bg-destructive/10 px-3 py-2 text-xs" role="alert">
            <span className="text-destructive">{error}</span>
            <div className="flex gap-2">
              <button onClick={session.retry} className="underline">Retry</button>
              <button onClick={() => router.push("/")} className="underline">Back home</button>
            </div>
          </div>
        )}
        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      </>
    );
  }

  return (
    <>
      <div className="flex h-dvh min-h-0 flex-col overflow-hidden bg-background text-foreground">
        <GlobalHeader
          onToggleCommandPalette={() => setPaletteOpen(true)}
          onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
          currentRun={currentRun}
          connectionStatus={session.error ? "error" : connection}
        />
        {error && (
          <div
            className="flex items-center justify-between gap-3 border-b border-destructive/30 bg-destructive/10 px-3 py-2 text-xs"
            role="alert"
          >
            <span className="text-destructive">{error}</span>
            <div className="flex gap-2">
              <button onClick={session.retry} className="underline">Retry</button>
              <button onClick={() => router.push("/")} className="underline">Back home</button>
            </div>
          </div>
        )}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          <AppShell
            sidebar={sidebar}
            conversation={<ConversationPane />}
            workbench={<WorkbenchPane />}
          />
        </div>
      </div>

      {mobileSidebarOpen && (
        <button
          className="fixed inset-0 z-40 bg-black/40"
          onClick={() => setMobileSidebarOpen(false)}
          aria-label="Close sidebar"
        />
      )}

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </>
  );
}
