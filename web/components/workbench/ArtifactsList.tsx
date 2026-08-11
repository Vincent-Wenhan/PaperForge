"use client";

import { ArtifactCard } from "../ArtifactCard";
import { EmptyState } from "../Skeleton";

export function ArtifactsList({ artifacts }: { artifacts: any[] }) {
  if (!artifacts || artifacts.length === 0) {
    return (
      <EmptyState
        icon="📦"
        title="No artifacts yet"
        description="Run the pipeline to generate artifacts. Capability cards, PRDs, and verification reports will appear here."
      />
    );
  }
  return (
    <div className="h-full overflow-y-auto p-3 space-y-2">
      {artifacts.map((artifact) => (
        <ArtifactCard
          key={artifact.id}
          type={artifact.type}
          path={artifact.path || ""}
          artifactId={artifact.id}
          data={artifact.data}
        />
      ))}
    </div>
  );
}
