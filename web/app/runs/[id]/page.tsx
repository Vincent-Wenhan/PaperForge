"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAppStore, type Run } from "@/lib/store";
import { Sidebar } from "@/components/Sidebar";
import { ChatPanel } from "@/components/ChatPanel";
import { PreviewPanel } from "@/components/PreviewPanel";
import { GlobalHeader } from "@/components/shell/GlobalHeader";
import { CommandPalette } from "@/components/dialogs/CommandPalette";

export default function RunWorkspacePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [runs, setRuns] = useState<any[]>([]);
  const [library, setLibrary] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);

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
  };

  if (loading) {
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
            <div className="flex-1 flex items-center justify-center text-muted-foreground">
              Loading run...
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
            onRunsChanged={loadRuns}
            onLibraryChanged={loadLibrary}
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
          <ChatPanel />
          <PreviewPanel />
        </div>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </>
  );
}
