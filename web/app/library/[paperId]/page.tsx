"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { CapabilityCardView } from "@/components/CapabilityCardView";

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
  const [data, setData] = useState<PaperDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  if (error) {
    return (
      <div className="flex h-screen items-center justify-center text-destructive">
        {error}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex h-screen items-center justify-center text-muted-foreground">
        Loading paper...
      </div>
    );
  }

  const { paper, capability_card } = data;

  return (
    <div className="min-h-screen p-6">
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
  );
}
