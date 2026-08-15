"use client";

import { useState } from "react";
import type { AgentStep, Approval, Message } from "@/lib/store";
import type { ToolActivity } from "@/lib/project-tools";

// Central presentation map: raw tool names are never shown to the user in the
// normal view (doc 7.3). Expand for raw args/result.
export const TOOL_PRESENTATION: Record<string, { title: string; category: string }> = {
  parse_paper: { title: "Parse paper", category: "research" },
  compose_capabilities: { title: "Compose capabilities", category: "planning" },
  plan_product: { title: "Plan product", category: "planning" },
  generate_nextjs_app: { title: "Generate app", category: "code" },
  verify_app: { title: "Verify app", category: "verification" },
  run_in_sandbox: { title: "Start preview", category: "runtime" },
};

function toolTitle(name: string): string {
  return TOOL_PRESENTATION[name]?.title ?? name;
}

export type ActivityItem =
  | { type: "tool"; activity: ToolActivity }
  | { type: "step"; step: AgentStep }
  | { type: "approval"; approval: Approval };

const STEP_ICON: Record<string, string> = {
  pending: "○",
  running: "●",
  completed: "✓",
  failed: "✗",
};

function statusColor(status: string): string {
  if (status === "failed") return "text-destructive";
  if (status === "completed") return "text-green-600";
  if (status === "running") return "text-blue-500";
  return "text-muted-foreground";
}

function StepRow({ step }: { step: AgentStep }) {
  const running = step.status === "running";
  return (
    <div className="flex items-start gap-2 text-xs py-0.5">
      <span className={statusColor(step.status)}>{STEP_ICON[step.status]}</span>
      <span className="font-medium">{step.title ?? step.kind ?? step.id.slice(0, 12)}</span>
      {running && step.percent !== undefined && (
        <span className="text-muted-foreground">{Math.round(step.percent)}%</span>
      )}
      {(step.status === "failed" && step.detail) && (
        <span className="text-destructive truncate">{step.detail}</span>
      )}
      {step.summary && step.status === "completed" && (
        <span className="text-muted-foreground truncate">{step.summary}</span>
      )}
    </div>
  );
}

function ToolRow({ activity }: { activity: ToolActivity }) {
  const [expanded, setExpanded] = useState(false);
  const done = activity.status === "completed";

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-1.5 bg-muted/40 flex items-center justify-between text-xs hover:bg-muted"
      >
        <span className={"flex items-center gap-2 " + statusColor(done ? "completed" : "running")}>
          <span>{done ? "✓" : "●"}</span>
          <span className="font-medium">{toolTitle(activity.name)}</span>
        </span>
        <span className="text-muted-foreground">{expanded ? "▲" : "▼"}</span>
      </button>
      {expanded && (
        <div className="p-2 space-y-2">
          {activity.args !== undefined && (
            <Details label="Input" value={activity.args} />
          )}
          {done && activity.result !== undefined && (
            <Details label="Output" value={activity.result} />
          )}
        </div>
      )}
    </div>
  );
}

function Details({ label, value }: { label: string; value: unknown }) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div>
      <div className="text-xs font-semibold mb-1">{label}</div>
      <pre className="text-xs overflow-x-auto bg-muted/30 p-2 rounded max-h-48 overflow-y-auto whitespace-pre-wrap break-words">
        {text}
      </pre>
    </div>
  );
}

export function ActivityTimeline({ items }: { items: ActivityItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="my-2 space-y-1.5">
      {items.map((item, i) => {
        if (item.type === "tool") return <ToolRow key={item.activity.id + i} activity={item.activity} />;
        if (item.type === "step") return <StepRow key={item.step.id + i} step={item.step} />;
        return <StepRow key={item.approval.approval_id + i} step={{ id: item.approval.approval_id, status: "running", title: "Waiting for approval" }} />;
      })}
    </div>
  );
}
