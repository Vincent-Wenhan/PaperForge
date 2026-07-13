"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAppStore, type Paper, type Run } from "@/lib/store";
import { useIsMobile, useIsTablet } from "@/lib/useMediaQuery";
import { Sidebar } from "@/components/Sidebar";
import { ChatPanel } from "@/components/ChatPanel";
import { PreviewPanel } from "@/components/PreviewPanel";
import { ResizableDivider } from "@/components/shell/ResizableDivider";
import { GlobalHeader } from "@/components/shell/GlobalHeader";
import { CommandPalette } from "@/components/dialogs/CommandPalette";
import { SkeletonMessage, SidebarSkeleton } from "@/components/Skeleton";

const SIDEBAR_WIDTH_KEY = "paperforge.sidebarWidth";
const CHAT_WIDTH_KEY = "paperforge.chatWidth";
const DEFAULT_SIDEBAR_WIDTH = 260;
const DEFAULT_CHAT_WIDTH = 480;

export default function RunWorkspacePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const isMobile = useIsMobile();
  const isTablet = useIsTablet();
  const [runs, setRuns] = useState<any[]>([]);
  const [library, setLibrary] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [activePanel, setActivePanel] = useState<"chat" | "preview">("chat");
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_SIDEBAR_WIDTH);
  const [chatWidth, setChatWidth] = useState(DEFAULT_CHAT_WIDTH);

  const setCurrentRun = useAppStore((s) => s.setCurrentRun);
  const setSandbox = useAppStore((s) => s.setSandbox);
  const setArtifacts = useAppStore((s) => s.setArtifacts);
  const setPendingApprovals = useAppStore((s) => s.setPendingApprovals);

  const loadRuns = useCallback(() => {
    api.listRuns().then(setRuns).catch(console.error);
  }, []);
  const loadLibrary = useCallback(() => {
    api.listLibrary().then((resp) => setLibrary(resp.papers || [])).catch(console.error);
  }, []);

  useEffect(() => {
    Promise.all([api.listRuns(), api.listLibrary()])
      .then(([runsResp, libResp]) => {
        setRuns(runsResp);
        setLibrary(libResp.papers || []);
      })
      .catch(console.error);
  }, []);

  useEffect(() => {
    if (!params.id) return;
    setLoading(true);
    setError(null);
    Promise.all([
      api.getRun(params.id),
      api.listArtifacts(params.id, true),
      api.listApprovals(params.id),
    ])
      .then(([run, arts, approvals]) => {
        setCurrentRun(run as Run);
        setArtifacts(arts);
        const pending = approvals.filter((a) => a.status === "pending");
        setPendingApprovals(pending);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || "Failed to load run");
        setLoading(false);
      });
  }, [params.id, setCurrentRun, setArtifacts, setPendingApprovals]);

  // Ponytail: load persisted panel widths from localStorage.
  useEffect(() => {
    try {
      const sw = localStorage.getItem(SIDEBAR_WIDTH_KEY);
      const cw = localStorage.getItem(CHAT_WIDTH_KEY);
      if (sw) setSidebarWidth(Math.max(200, Math.min(480, parseInt(sw, 10))));
      if (cw) setChatWidth(Math.max(360, Math.min(900, parseInt(cw, 10))));
    } catch {
      // localStorage may be unavailable (SSR, privacy mode); defaults are fine.
    }
  }, []);

  const handleSidebarResize = useCallback((delta: number) => {
    setSidebarWidth((prev) => {
      const next = Math.max(200, Math.min(480, prev + delta));
      try {
        localStorage.setItem(SIDEBAR_WIDTH_KEY, String(next));
      } catch {
        // ignore
      }
      return next;
    });
  }, []);

  const handleChatResize = useCallback((delta: number) => {
    setChatWidth((prev) => {
      const next = Math.max(360, Math.min(900, prev + delta));
      try {
        localStorage.setItem(CHAT_WIDTH_KEY, String(next));
      } catch {
        // ignore
      }
      return next;
    });
  }, []);

  useEffect(() => {
    if (!params.id) return;
    api.listSandboxes()
      .then((sandboxes) => {
        const runSb = sandboxes.filter((s) => s.run_id === params.id);
        if (runSb.length > 0) {
          const latest = runSb.sort((a, b) =>
            String(b.started_at).localeCompare(String(a.started_at))
          )[0];
          setSandbox(latest);
        } else {
          setSandbox(null);
        }
      })
      .catch(() => setSandbox(null));
  }, [params.id, setSandbox]);

  // Ponytail: also fetch the latest sandbox via the dedicated endpoint as a
  // fallback in case listSandboxes is filtered or returns stale data.
  useEffect(() => {
    if (!params.id) return;
    api.getLatestSandboxForRun(params.id)
      .then((sb) => {
        if (sb) setSandbox(sb);
      })
      .catch(() => {});
  }, [params.id, setSandbox]);

  // Command palette shortcut (Ctrl/Cmd+K)
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
          <GlobalHeader onToggleCommandPalette={() => setPaletteOpen(true)} />
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

  if (error) {
    return (
      <>
        <div className="flex h-screen w-screen flex-col overflow-hidden">
          <GlobalHeader onToggleCommandPalette={() => setPaletteOpen(true)} />
          <div className="flex flex-1 overflow-hidden">
            <Sidebar
              runs={runs}
              library={library}
              onNewRun={handleNewRun}
              onSelectRun={handleSelectRun}
            />
            <div className="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground">
              <p className="text-destructive">{error}</p>
              <button
                onClick={() => router.push("/")}
                className="px-3 py-1.5 border rounded hover:bg-accent"
              >
                Back to home
              </button>
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
          onToggleSidebar={
            isMobile
              ? () => setMobileSidebarOpen((v) => !v)
              : () => setSidebarCollapsed((v) => !v)
          }
        />
        <div className="flex flex-1 overflow-hidden">
          {isMobile && mobileSidebarOpen ? (
            <Sidebar
              runs={runs}
              library={library}
              onNewRun={handleNewRun}
              onSelectRun={handleSelectRun}
              onRunsChanged={loadRuns}
              onLibraryChanged={loadLibrary}
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
            <>
              <div
                className="flex flex-col overflow-hidden bg-muted/30"
                style={{ width: `${sidebarWidth}px`, minWidth: "200px" }}
              >
                <Sidebar
                  runs={runs}
                  library={library}
                  onNewRun={handleNewRun}
                  onSelectRun={handleSelectRun}
                  onRunsChanged={loadRuns}
                  onLibraryChanged={loadLibrary}
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
              </div>
              <ResizableDivider onResize={handleSidebarResize} />
            </>
          )}
          {showSinglePanel ? (
            <div className="flex-1 flex flex-col overflow-hidden">
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
                  Preview
                </button>
              </div>
              <div className="flex-1 overflow-hidden">
                {activePanel === "chat" ? <ChatPanel /> : <PreviewPanel />}
              </div>
            </div>
          ) : (
            <>
              <div
                className="flex flex-col overflow-hidden border-r border-border"
                style={{ width: `${chatWidth}px`, minWidth: "360px" }}
              >
                <ChatPanel />
              </div>
              <ResizableDivider onResize={handleChatResize} />
              <PreviewPanel />
            </>
          )}
        </div>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </>
  );
}
