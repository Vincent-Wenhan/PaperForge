"use client";

import { useEffect, useState } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ChatPanel } from "@/components/ChatPanel";
import { PreviewPanel } from "@/components/PreviewPanel";
import { useAppStore } from "@/lib/store";
import { api } from "@/lib/api";

export default function Home() {
  const [runs, setRuns] = useState<any[]>([]);
  const [library, setLibrary] = useState<any[]>([]);
  const currentRun = useAppStore((s) => s.currentRun);
  const setCurrentRun = useAppStore((s) => s.setCurrentRun);

  useEffect(() => {
    Promise.all([api.listRuns(), api.listLibrary()])
      .then(([runsResp, libResp]) => {
        setRuns(runsResp);
        setLibrary(libResp.papers || []);
      })
      .catch(console.error);
  }, []);

  const handleNewRun = async () => {
    const run = await api.createRun("New Run");
    setRuns((prev) => [run, ...prev]);
    setCurrentRun(run);
  };

  const handleSelectRun = async (runId: string) => {
    const run = await api.getRun(runId);
    setCurrentRun(run);
  };

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
