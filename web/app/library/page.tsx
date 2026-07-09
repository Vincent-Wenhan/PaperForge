"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Sidebar } from "@/components/Sidebar";
import type { Paper } from "@/lib/store";

export default function LibraryPage() {
  const router = useRouter();
  const [runs, setRuns] = useState<any[]>([]);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.listRuns(), api.listLibrary()])
      .then(([runsResp, libResp]) => {
        setRuns(runsResp);
        setPapers(libResp.papers || []);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
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
        library={papers}
        onNewRun={handleNewRun}
        onSelectRun={handleSelectRun}
      />
      <div className="flex-1 overflow-y-auto p-6">
        <h1 className="text-2xl font-semibold mb-4">Paper Library</h1>
        {loading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-16 w-full bg-muted animate-pulse rounded"
              />
            ))}
          </div>
        ) : papers.length === 0 ? (
          <p className="text-muted-foreground">
            No papers in the library yet. Upload a paper from the sidebar.
          </p>
        ) : (
          <ul className="divide-y divide-border border border-border rounded">
            {papers.map((p) => (
              <li
                key={p.paper_id}
                className="p-4 hover:bg-accent cursor-pointer flex items-center justify-between"
                onClick={() => router.push(`/library/${p.paper_id}`)}
              >
                <div className="flex flex-col">
                  <span className="font-medium">{p.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {p.status} · {p.created_at ? new Date(p.created_at).toLocaleString() : ""}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
