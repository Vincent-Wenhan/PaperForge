"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Sidebar } from "@/components/Sidebar";
import { CapabilityCardView } from "@/components/CapabilityCardView";
import type { Paper, Run } from "@/lib/store";

interface PaperDetail {
  paper: Paper;
  capability_card: any;
}

function formatDate(s?: string | null): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString();
  } catch {
    return s;
  }
}

export default function PaperDetailPage() {
  const params = useParams<{ paperId: string }>();
  const router = useRouter();
  const [runs, setRuns] = useState<Run[]>([]);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [data, setData] = useState<PaperDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadAll = useCallback(() => {
    Promise.all([api.listRuns(), api.listLibrary()])
      .then(([runsResp, libResp]) => {
        setRuns(runsResp);
        setPapers(libResp.papers || []);
      })
      .catch(console.error);
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const reloadPaper = useCallback(() => {
    if (!params.paperId) return;
    api
      .getPaper(params.paperId)
      .then((detail: PaperDetail) => {
        setData(detail);
        setError(null);
      })
      .catch((err) => setError(err.message || "Failed to load paper"));
  }, [params.paperId]);

  useEffect(() => {
    reloadPaper();
  }, [reloadPaper]);

  const handleNewRun = async () => {
    const run = await api.createRun("New Run");
    setRuns((prev) => [run, ...prev]);
    router.push(`/runs/${run.id}`);
  };

  if (error) {
    return (
      <div className="flex h-screen w-screen overflow-hidden">
        <Sidebar
          runs={runs}
          library={papers}
          onNewRun={handleNewRun}
          onSelectRun={(id) => router.push(`/runs/${id}`)}
          onRunsChanged={loadAll}
          onLibraryChanged={loadAll}
          onOpenPaper={(paperId) => router.push(`/library/${paperId}`)}
        />
        <div className="flex-1 flex items-center justify-center text-destructive">
          {error}
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex h-screen w-screen overflow-hidden">
        <Sidebar
          runs={runs}
          library={papers}
          onNewRun={handleNewRun}
          onSelectRun={(id) => router.push(`/runs/${id}`)}
          onRunsChanged={loadAll}
          onLibraryChanged={loadAll}
          onOpenPaper={(paperId) => router.push(`/library/${paperId}`)}
        />
        <div className="flex-1 flex items-center justify-center text-muted-foreground">
          Loading paper...
        </div>
      </div>
    );
  }

  const { paper, capability_card } = data;
  const card = capability_card || {};
  const referencedRuns = runs.filter(
    (r) => (paper.title && r.title?.includes(paper.title)) || false
  );

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <Sidebar
        runs={runs}
        library={papers}
        onNewRun={handleNewRun}
        onSelectRun={(id) => router.push(`/runs/${id}`)}
        onRunsChanged={loadAll}
        onLibraryChanged={loadAll}
        onOpenPaper={(paperId) => router.push(`/library/${paperId}`)}
      />
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto p-6 space-y-6">
          <button
            onClick={() => router.push("/library")}
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            ← Back to library
          </button>

          <header className="space-y-1">
            <h1 className="text-2xl font-semibold">{paper.title}</h1>
            <div className="text-sm text-muted-foreground space-x-2">
              <span>{paper.paper_id}</span>
            </div>
          </header>

          <section className="border border-border rounded-md p-4 space-y-2 text-sm">
            <div className="grid grid-cols-3 gap-y-1">
              <span className="text-muted-foreground">Status</span>
              <span className="col-span-2">
                <span className="px-1.5 py-0.5 bg-muted rounded">
                  {paper.status}
                </span>
              </span>

              <span className="text-muted-foreground">Uploaded</span>
              <span className="col-span-2">{formatDate(paper.created_at)}</span>

              <span className="text-muted-foreground">Parsed</span>
              <span className="col-span-2">{formatDate(paper.parsed_at)}</span>
            </div>
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-muted-foreground uppercase">
              Capability Card
            </h2>
            {capability_card ? (
              <CapabilityCardView card={capability_card} />
            ) : (
              <div className="border border-dashed border-border rounded-md p-4 text-sm text-muted-foreground">
                No capability card generated yet.
              </div>
            )}
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-muted-foreground uppercase">
              Referenced Runs
            </h2>
            {referencedRuns.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No runs reference this paper.
              </p>
            ) : (
              <ul className="border border-border rounded-md divide-y divide-border">
                {referencedRuns.map((r) => (
                  <li key={r.id}>
                    <button
                      onClick={() => router.push(`/runs/${r.id}`)}
                      className="w-full text-left px-3 py-2 hover:bg-accent flex justify-between items-center"
                    >
                      <span className="font-medium">{r.title}</span>
                      <span className="text-xs text-muted-foreground">
                        {r.status}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="flex gap-2">
            <button
              onClick={() => router.push(`/library/${paper.paper_id}/pdf`)}
              className="px-3 py-1.5 text-sm border border-border rounded hover:bg-accent"
            >
              Download PDF
            </button>
          </section>
        </div>
      </div>
    </div>
  );
}
