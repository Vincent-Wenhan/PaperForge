"use client";

import { useState } from "react";
import { ToolCallCard } from "./ToolCallCard";

interface AgentActivityProps {
  events: { id: string; type: string; data: any; run_id: string }[];
}

interface ActivityGroup {
  id: string;
  toolName: string;
  args: any;
  result?: any;
  callId?: string;
  relatedEvents: { id: string; type: string; data: any }[];
}

const TOOL_LABELS: Record<string, string> = {
  parse_paper: "Parsing paper",
  compose_capabilities: "Composing capabilities",
  plan_product: "Planning product",
  generate_nextjs_app: "Generating app",
  verify_app: "Verifying app",
  run_in_sandbox: "Starting preview",
  finish: "Finishing",
};

const STATUS_ICON: Record<string, string> = {
  pending: "○",
  running: "●",
  complete: "✓",
  error: "✗",
};

function groupActivityEvents(
  events: { id: string; type: string; data: any }[],
): ActivityGroup[] {
  const groups: ActivityGroup[] = [];
  const pendingByCallId = new Map<string, number>();

  for (const event of events) {
    if (event.type === "tool.call") {
      const toolName = event.data.name || "unknown";
      const args = event.data.args || {};
      const callId = event.data.id;
      const group: ActivityGroup = {
        id: event.id || `${toolName}-${groups.length}`,
        toolName,
        args,
        callId,
        relatedEvents: [event],
      };
      if (callId) pendingByCallId.set(callId, groups.length);
      groups.push(group);
    } else if (event.type === "tool.result") {
      const callId = event.data.call_id;
      const idx = callId ? pendingByCallId.get(callId) : undefined;
      if (idx !== undefined) {
        groups[idx].result = event.data.result;
        groups[idx].relatedEvents.push(event);
      } else {
        groups.push({
          id: event.id || `result-${groups.length}`,
          toolName: event.data.name || "tool",
          args: {},
          result: event.data.result,
          relatedEvents: [event],
        });
      }
    } else {
      const lastGroup = groups[groups.length - 1];
      if (lastGroup) {
        lastGroup.relatedEvents.push(event);
      } else {
        groups.push({
          id: event.id || `misc-${groups.length}`,
          toolName: event.type,
          args: {},
          relatedEvents: [event],
        });
      }
    }
  }

  return groups;
}

function deriveStatus(group: ActivityGroup): string {
  if (group.result !== undefined) {
    try {
      const parsed =
        typeof group.result === "string"
          ? JSON.parse(group.result)
          : group.result;
      if (parsed?.ok === false) return "error";
    } catch {
      // Non-JSON result, assume complete
    }
    return "complete";
  }
  return "running";
}

export function AgentActivity({ events }: AgentActivityProps) {
  const [expanded, setExpanded] = useState(false);

  if (events.length === 0) return null;

  const groups = groupActivityEvents(events);
  const completed = groups.filter((g) => deriveStatus(g) === "complete").length;
  const errored = groups.filter((g) => deriveStatus(g) === "error").length;
  const running = groups.find((g) => deriveStatus(g) === "running");

  const summary = running
    ? `${TOOL_LABELS[running.toolName] || running.toolName}…`
    : errored > 0
      ? `${completed}/${groups.length} steps · ${errored} failed`
      : `${completed}/${groups.length} steps`;

  const headerIcon = running
    ? STATUS_ICON.running
    : errored > 0
      ? STATUS_ICON.error
      : STATUS_ICON.complete;

  return (
    <div className="border border-border rounded-lg bg-muted/30 my-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-2 flex items-center justify-between text-sm hover:bg-muted/50"
      >
        <span className="flex items-center gap-2">
          <span className={running ? "text-blue-500" : errored > 0 ? "text-destructive" : "text-green-600"}>
            {headerIcon}
          </span>
          <span className="font-medium">{summary}</span>
        </span>
        <span className="text-xs text-muted-foreground">
          {groups.length} tool{groups.length === 1 ? "" : "s"}
          {expanded ? " ▲" : " ▼"}
        </span>
      </button>
      {expanded && (
        <div className="border-t border-border p-2 space-y-1">
          {groups.map((group) => {
            const status = deriveStatus(group);
            return (
              <ToolCallCard
                key={group.id}
                name={group.toolName}
                args={group.args}
                result={group.result}
                callId={group.callId}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
