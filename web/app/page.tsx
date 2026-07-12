"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Sidebar } from "@/components/Sidebar";
import { GlobalHeader } from "@/components/shell/GlobalHeader";
import { CommandPalette } from "@/components/dialogs/CommandPalette";

export default function Home() {
  const router = useRouter();
  const [runs, setRuns] = useState<any[]>([]);
  const [library, setLibrary] = useState<any[]>([]);
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    Promise.all([api.listRuns(), api.listLibrary()])
      .then(([runsResp, libResp]) => {
        setRuns(runsResp);
        setLibrary(libResp.papers || []);
      })
      .catch(console.error);
  }, []);

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
            Select a run or create a new one to get started.
          </div>
        </div>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </>
  );
}
