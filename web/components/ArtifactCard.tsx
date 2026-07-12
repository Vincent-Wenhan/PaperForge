"use client";

import { useState } from "react";
import { CapabilityCardView } from "./CapabilityCardView";
import { PrdView } from "./PrdView";
import { VerificationReportView } from "./VerificationReportView";
import { api } from "@/lib/api";

interface ArtifactCardProps {
  type: string;
  path: string;
  artifactId: string;
  data?: any;
  onRenamed?: () => void;
  onDeleted?: () => void;
}

export function ArtifactCard({
  type,
  path,
  artifactId,
  data,
  onRenamed,
  onDeleted,
}: ArtifactCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const label = type.replace(/_/g, " ");

  const handleRename = async () => {
    setMenuOpen(false);
    const display = prompt("Display name:", label);
    if (!display) return;
    try {
      await api.renameArtifact(artifactId, display);
      onRenamed?.();
    } catch (err) {
      console.error(err);
    }
  };

  const handleDownload = async () => {
    setMenuOpen(false);
    try {
      const blob = await api.downloadArtifact(artifactId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${artifactId}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error(err);
    }
  };

  const handleDelete = async () => {
    setMenuOpen(false);
    if (!confirm(`Delete ${label}?`)) return;
    try {
      await api.deleteArtifact(artifactId);
      onDeleted?.();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="my-2 border border-border rounded-lg overflow-hidden">
      <div className="relative">
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full px-3 py-2 bg-muted/50 flex items-center justify-between text-sm hover:bg-muted"
        >
          <span className="font-medium capitalize">{label}</span>
          <span className="text-xs text-muted-foreground">
            {expanded ? "▼" : "▶"}
          </span>
        </button>
        <button
          onClick={() => setMenuOpen(!menuOpen)}
          className="absolute right-6 top-1.5 opacity-0 group-hover:opacity-100 hover:bg-accent rounded px-1 text-xs"
        >
          ···
        </button>
        {menuOpen && (
          <div className="absolute right-6 top-9 z-10 bg-background border border-border rounded shadow-md py-1 text-xs w-32">
            <button
              onClick={handleRename}
              className="block w-full text-left px-3 py-1.5 hover:bg-accent"
            >
              Rename
            </button>
            <button
              onClick={handleDownload}
              className="block w-full text-left px-3 py-1.5 hover:bg-accent"
            >
              Download
            </button>
            <button
              onClick={handleDelete}
              className="block w-full text-left px-3 py-1.5 hover:bg-accent text-destructive"
            >
              Delete
            </button>
          </div>
        )}
      </div>
      {expanded && (
        <div className="p-3">
          <div className="text-xs text-muted-foreground mb-2">
            Artifact: {artifactId}
          </div>
          <ArtifactContent type={type} data={data} path={path} />
        </div>
      )}
    </div>
  );
}

function ArtifactContent({
  type,
  data,
  path,
}: {
  type: string;
  data: any;
  path: string;
}) {
  // 1. Capability card
  if (type === "capability_card" || type === "capability-card") {
    const card = data?.card || data;
    return <CapabilityCardView card={card} />;
  }

  // 2. PRD
  if (type === "prd") {
    const prd = data?.prd || data;
    return <PrdView prd={prd} />;
  }

  // 3. Verification report
  if (type === "verification_report" || type === "verification-report" || type === "report") {
    const report = data?.report || data;
    return <VerificationReportView report={report} />;
  }

  // 4. Composition / generic — render raw JSON
  return (
    <pre className="text-xs overflow-x-auto bg-muted/30 p-2 rounded">
      {JSON.stringify(data ?? { path }, null, 2)}
    </pre>
  );
}
