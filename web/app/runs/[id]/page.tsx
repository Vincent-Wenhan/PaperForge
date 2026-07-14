"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Panel,
  PanelGroup,
  PanelResizeHandle,
} from "react-resizable-panels";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { useRunSession } from "@/lib/useRunSession";
import { useIsMobile, useIsTablet } from "@/lib/useMediaQuery";
import { Sidebar } from "@/components/Sidebar";
import { ChatPanel } from "@/components/ChatPanel";
import { PreviewPanel } from "@/components/PreviewPanel";
import { GlobalHeader } from "@/components/shell/GlobalHeader";
import { CommandPalette } from "@/components/dialogs/CommandPalette";
import { SkeletonMessage, SidebarSkeleton } from "@/components/Skeleton";

export default function RunWorkspacePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const isMobile = useIsMobile();
  const isTablet = useIsTablet();
  const [runs, setRuns] = useState<any[]>([]);
  const [library, setLibrary] = useState<any[]>([]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [activePanel, setActivePanel] = useState<"chat" | "preview">("chat");
  const session = useRunSession(params.id);
  const currentRun = useAppStore((s) => s.currentRun);
  const currentRunId = useAppStore((s) => s.currentRun?.id);

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

  const handleNewRun = async () => {
    const run = await api.createRun("New Run");
    setRuns((prev) => [run, ...prev]);
    router.push(`/runs/${run.id}`);
  };

  const handleSelectRun = (runId: string) => {
    router.push(`/runs/${runId}`);
    setMobileSidebarOpen(false);
  };

  if (loading) {
    return (
      <>
        <div className="flex h-screen w-screen flex-col overflow-hidden">
           <GlobalHeader
             onToggleCommandPalette={() => setPaletteOpen(true)}
             currentRun={currentRun}
             connectionStatus={session.error ? "error" : "connecting"}
           />
          <div className="flex flex-1 overflow-hidden">
            <SidebarSkeleton />
            <div className="flex-1 p-4 space-y-4">
              <SkeletonMessage />
              <SkeletonMessage />
            </div>
          </div>
        </div>
        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      </>
    );
  }

  // On tablet/mobile, only show one panel at a time with a toggle.
  const showSinglePanel = isMobile || isTablet;

  return (
    <>
      <div className="flex h-screen w-screen flex-col overflow-hidden">
         <GlobalHeader
           onToggleCommandPalette={() => setPaletteOpen(true)}
           currentRun={currentRun}
           connectionStatus={session.error ? "error" : session.loading ? "connecting" : "connected"}
         />
        <div className="flex flex-1 overflow-hidden">
          {isMobile && mobileSidebarOpen ? (
            <Sidebar
              runs={runs}
              library={library}
              onNewRun={handleNewRun}
              onSelectRun={handleSelectRun}
              currentRunId={currentRunId}
              onCloseMobile={() => setMobileSidebarOpen(false)}
              onOpenPaper={(paperId) => router.push(`/library/${paperId}`)}
              onAttachPaper={(paper) => {
                const store = useAppStore.getState();
                store.addAttachment({
                  id: `paper-${paper.paper_id}`,
                  type: "paper",
                  name: paper.title,
                  paperId: paper.paper_id,
                });
              }}
            />
          ) : (
            <Sidebar
              runs={runs}
              library={library}
              onNewRun={handleNewRun}
              onSelectRun={handleSelectRun}
              currentRunId={currentRunId}
              collapsed={sidebarCollapsed}
              onToggleCollapse={() =>
                setSidebarCollapsed((v) => !v)
              }
              onOpenPaper={(paperId) =>
                router.push(`/library/${paperId}`)
              }
              onAttachPaper={(paper) => {
                const store = useAppStore.getState();
                store.addAttachment({
                  id: `paper-${paper.paper_id}`,
                  type: "paper",
                  name: paper.title,
                  paperId: paper.paper_id,
                });
              }}
            />
          )}

          {showSinglePanel ? (
            <div className="flex-1 flex flex-col overflow-hidden">
              {error && (
                <div className="flex items-center justify-between gap-3 border-b border-destructive/30 bg-destructive/10 px-3 py-2 text-xs" role="alert">
                  <span className="text-destructive">{error}</span>
                  <div className="flex gap-2">
                    <button onClick={session.retry} className="underline">Retry</button>
                    <button onClick={() => router.push("/")} className="underline">Back home</button>
                  </div>
                </div>
              )}
              <div className="flex border-b border-border bg-muted/30" role="tablist">
                <button
                  role="tab"
                  aria-selected={activePanel === "chat"}
                  onClick={() => setActivePanel("chat")}
                  className={`flex-1 px-4 py-2 text-sm border-b-2 ${
                    activePanel === "chat"
                      ? "border-primary font-medium bg-background"
                      : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/50"
                  }`}
                >
                  Chat
                </button>
                <button
                  role="tab"
                  aria-selected={activePanel === "preview"}
                  onClick={() => setActivePanel("preview")}
                  className={`flex-1 px-4 py-2 text-sm border-b-2 ${
                    activePanel === "preview"
                      ? "border-primary font-medium bg-background"
                      : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/50"
                  }`}
                >
                  Workbench
                </button>
              </div>
              <div className="flex-1 overflow-hidden">
                {activePanel === "chat" ? <ChatPanel /> : <PreviewPanel />}
              </div>
            </div>
          ) : (
            <>
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
              <PanelGroup direction="horizontal" autoSaveId="paperforge-layout">
                <Panel defaultSize={42} minSize={28}>
                  <ChatPanel />
                </Panel>
                <PanelResizeHandle className="w-px bg-border hover:bg-primary/40 transition-colors" />
                <Panel defaultSize={58} minSize={30}>
                  <PreviewPanel />
                </Panel>
              </PanelGroup>
            </>
          )}
        </div>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </>
  );
}
