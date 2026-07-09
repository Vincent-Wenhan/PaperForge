"use client";

import { useState } from "react";

interface ArtifactCardProps {
  type: string;
  path: string;
  artifactId: string;
  data?: any;
}

export function ArtifactCard({ type, path, artifactId, data }: ArtifactCardProps) {
  const [expanded, setExpanded] = useState(false);

  const label = type.replace(/_/g, " ");

  return (
    <div className="my-2 border border-border rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-2 bg-muted/50 flex items-center justify-between text-sm hover:bg-muted"
      >
        <span className="font-medium capitalize">{label}</span>
        <span className="text-xs text-muted-foreground">
          {expanded ? "▼" : "▶"}
        </span>
      </button>
      {expanded && (
        <div className="p-3">
          <div className="text-xs text-muted-foreground mb-2">
            Artifact: {artifactId}
          </div>
          <pre className="text-xs overflow-x-auto bg-muted/30 p-2 rounded">
            {JSON.stringify(data ?? { path }, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
