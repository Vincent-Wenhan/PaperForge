"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Sidebar } from "@/components/Sidebar";

export default function Home() {
  const router = useRouter();
  const [runs, setRuns] = useState<any[]>([]);
  const [library, setLibrary] = useState<any[]>([]);

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
    router.push(`/runs/${run.id}`);
  };

  const handleSelectRun = (runId: string) => {
    router.push(`/runs/${runId}`);
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <Sidebar
        runs={runs}
        library={library}
        onNewRun={handleNewRun}
        onSelectRun={handleSelectRun}
      />
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        Select a run or create a new one to get started.
      </div>
    </div>
  );
}
