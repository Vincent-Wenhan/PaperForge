"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAppStore, type Run } from "@/lib/store";
import { Sidebar } from "@/components/Sidebar";
import { ChatPanel } from "@/components/ChatPanel";
import { PreviewPanel } from "@/components/PreviewPanel";

export default function RunWorkspacePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [runs, setRuns] = useState<any[]>([]);
  const [library, setLibrary] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const setCurrentRun = useAppStore((s) => s.setCurrentRun);

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
    api
      .getRun(params.id)
      .then((run: Run) => {
        setCurrentRun(run);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || "Failed to load run");
        setLoading(false);
      });
  }, [params.id, setCurrentRun]);

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
      <div className="flex h-screen w-screen overflow-hidden">
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
    );
  }

  if (error) {
    return (
      <div className="flex h-screen w-screen overflow-hidden">
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
    );
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <Sidebar
        runs={runs}
        library={library}
        onNewRun={handleNewRun}
        onSelectRun={handleSelectRun}
      />
      <ChatPanel />
      <PreviewPanel />
    </div>
  );
}
