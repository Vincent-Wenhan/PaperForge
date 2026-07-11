"use client";

import { useState } from "react";
import { CapabilityCardView } from "./CapabilityCardView";
import { PrdView } from "./PrdView";
import { VerificationReportView } from "./VerificationReportView";

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

