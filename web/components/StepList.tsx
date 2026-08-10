"use client";

import { memo } from "react";
import type { AgentStep } from "@/lib/store";

const KIND_LABELS: Record<string, string> = {
  paper_parse: "Reading paper",
  planning: "Planning",
  tool: "Running tool",
  codegen: "Generating code",
  edit: "Editing",
  build: "Building",
  test: "Verifying",
  preview: "Preview",
};

const STATUS_ICON: Record<AgentStep["status"], string> = {
  pending: "○",
  running: "●",
  completed: "✓",
  failed: "✗",
};

function StepRow({ step }: { step: AgentStep }) {
  const running = step.status === "running";
  return (
    <div className="flex items-start gap-2 text-xs py-0.5">
      <span
        className={
          running
            ? "text-blue-500"
            : step.status === "failed"
              ? "text-destructive"
              : step.status === "completed"
                ? "text-green-600"
                : "text-muted-foreground"
        }
      >
        {STATUS_ICON[step.status]}
      </span>
      <span className="font-medium">{step.title || (step.kind && KIND_LABELS[step.kind]) || step.id.slice(0, 12)}</span>
      {step.status === "running" && step.percent !== undefined && (
        <span className="text-muted-foreground">{Math.round(step.percent)}%</span>
      )}
      {step.detail && step.status === "failed" && (
        <span className="text-destructive truncate">{step.detail}</span>
      )}
      {step.summary && step.status === "completed" && (
        <span className="text-muted-foreground truncate">{step.summary}</span>
      )}
    </div>
  );
}

export const StepList = memo(function StepList({ steps }: { steps: AgentStep[] }) {
  if (steps.length === 0) return null;
  return (
    <div className="my-2 border border-border rounded-lg bg-muted/30 px-3 py-2">
      {steps.map((step) => (
        <StepRow key={step.id} step={step} />
      ))}
    </div>
  );
});
