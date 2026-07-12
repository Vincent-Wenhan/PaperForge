"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Sidebar } from "@/components/Sidebar";
import { CapabilityCardView } from "@/components/CapabilityCardView";
import type { Paper } from "@/lib/store";

interface PaperDetail {
  paper: {
    paper_id: string;
    title: string;
    pdf_path: string;
    status: string;
    created_at?: string;
    parsed_at?: string;
  };
  capability_card: any;
}

export default function PaperDetailPage() {
  const params = useParams<{ paperId: string }>();
  const router = useRouter();
  const [runs, setRuns] = useState<any[]>([]);
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

  useEffect(() => {
    if (!params.paperId) return;
    api
      .getPaper(params.paperId)
      .then((detail: PaperDetail) => {
        setData(detail);
        setError(null);
      })
      .catch((err) => {
        setError(err.message || "Failed to load paper");
      });
  }, [params.paperId]);

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
      <div className="flex-1 overflow-y-auto p-6">
        <button
          onClick={() => router.push("/library")}
          className="text-sm text-muted-foreground hover:text-foreground mb-4"
        >
          ← Back to library
        </button>
        <h1 className="text-2xl font-semibold mb-2">{paper.title}</h1>
        <p className="text-sm text-muted-foreground mb-6">
          Status: {paper.status}
          {paper.parsed_at && ` · Parsed: ${new Date(paper.parsed_at).toLocaleString()}`}
        </p>

        {capability_card ? (
          <CapabilityCardView card={capability_card} />
        ) : (
          <p className="text-muted-foreground">
            Capability card not yet generated for this paper.
          </p>
        )}
      </div>
    </div>
  );
}
