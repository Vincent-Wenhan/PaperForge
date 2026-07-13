"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";

export type MessagePartType =
  | "text"
  | "tool"
  | "artifact"
  | "approval"
  | "error";

interface BasePart {
  type: MessagePartType;
}

export interface TextPart extends BasePart {
  type: "text";
  text: string;
}

export interface ToolPartType extends BasePart {
  type: "tool";
  callId: string;
  name: string;
  args: any;
  result?: any;
}

export interface ArtifactPartType extends BasePart {
  type: "artifact";
  artifactId: string;
}

export interface ApprovalPartType extends BasePart {
  type: "approval";
  approvalId: string;
  tool: string;
  args: any;
}

export interface ErrorPartType extends BasePart {
  type: "error";
  message: string;
}

export type MessagePart =
  | TextPart
  | ToolPartType
  | ArtifactPartType
  | ApprovalPartType
  | ErrorPartType;

export function MessagePart({ part }: { part: MessagePart }) {
  switch (part.type) {
    case "text":
      return <TextPartView text={part.text} />;
    case "tool":
      return (
        <ToolPart
          name={part.name}
          args={part.args}
          callId={part.callId}
          result={part.result}
        />
      );
    case "artifact":
      return <ArtifactPart artifactId={part.artifactId} />;
    case "approval":
      return <ApprovalPart approval={part as any} />;
    case "error":
      return <ErrorPart message={part.message} />;
    default:
      return null;
  }
}

function TextPartView({ text }: { text: string }) {
  return (
    <div className="text-sm prose prose-sm max-w-none">
      <ReactMarkdown>{text}</ReactMarkdown>
    </div>
  );
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

interface ToolPartProps {
  name: string;
  args: any;
  callId?: string;
  result?: any;
}

export function ToolPart({ name, args, callId, result }: ToolPartProps) {
  const [expanded, setExpanded] = useState(false);

  let status: "pending" | "running" | "complete" | "error" = "running";
  if (result !== undefined) {
    try {
      const parsed =
        typeof result === "string" ? JSON.parse(result) : result;
      if (parsed?.ok === false) status = "error";
      else status = "complete";
    } catch {
      status = "complete";
    }
  }

  const summary = TOOL_LABELS[name] || name;
  const headerIcon = STATUS_ICON[status];

  return (
    <div className="my-1 border border-border rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-1.5 bg-muted/50 flex items-center justify-between text-xs hover:bg-muted"
      >
        <span className="flex items-center gap-2">
          <span
            className={
              status === "running"
                ? "text-blue-500"
                : status === "error"
                  ? "text-destructive"
                  : "text-green-600"
            }
          >
            {headerIcon}
          </span>
          <span className="font-mono">{summary}</span>
        </span>
        <span className="text-muted-foreground">
          {expanded ? "▲" : "▼"}
        </span>
      </button>
      {expanded && (
        <div className="p-2 space-y-2">
          {callId && (
            <div className="text-xs text-muted-foreground">
              Call ID: {callId}
            </div>
          )}
          <div>
            <div className="text-xs font-semibold mb-1">Args</div>
            <pre className="text-xs overflow-x-auto bg-muted/30 p-2 rounded">
              {JSON.stringify(args, null, 2)}
            </pre>
          </div>
          {result !== undefined && (
            <div>
              <div className="text-xs font-semibold mb-1">Result</div>
              <pre className="text-xs overflow-x-auto bg-muted/30 p-2 rounded max-h-64 overflow-y-auto">
                {typeof result === "string"
                  ? result
                  : JSON.stringify(result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface ArtifactPartProps {
  artifactId: string;
}

export function ArtifactPart({ artifactId }: ArtifactPartProps) {
  return (
    <div className="my-1 border border-border rounded-lg p-2 text-xs">
      <div className="font-mono">📦 Artifact: {artifactId}</div>
    </div>
  );
}

interface ApprovalPartProps {
  approval: any;
}

export function ApprovalPart({ approval }: ApprovalPartProps) {
  const [resolved, setResolved] = useState<"approved" | "rejected" | null>(
    approval.status === "pending" ? null : approval.status
  );

  const handle = (approved: boolean) => {
    setResolved(approved ? "approved" : "rejected");
  };

  const stepLabel = approval.tool || "unknown";

  return (
    <div className="border border-amber-400/60 bg-amber-50 dark:bg-amber-950/30 rounded-lg p-3 my-2">
      <div className="flex items-start justify-between mb-2">
        <div>
          <div className="text-sm font-semibold text-amber-900 dark:text-amber-200">
            PaperForge wants to {stepLabel.toLowerCase()}
          </div>
        </div>
        <div className="text-xs text-amber-700 dark:text-amber-300">
          {resolved === "approved"
            ? "Approved"
            : resolved === "rejected"
              ? "Rejected"
              : "Pending"}
        </div>
      </div>
      <div className="flex gap-2 mt-2">
        {!resolved && (
          <>
            <button
              onClick={() => handle(false)}
              className="px-3 py-1.5 text-xs font-medium bg-red-600 text-white rounded hover:bg-red-700"
            >
              Reject
            </button>
            <button
              onClick={() => handle(true)}
              className="px-3 py-1.5 text-xs font-medium bg-green-600 text-white rounded hover:bg-green-700"
            >
              Approve
            </button>
          </>
        )}
      </div>
    </div>
  );
}

interface ErrorPartProps {
  message: string;
}

export function ErrorPart({ message }: ErrorPartProps) {
  return (
    <div className="my-1 border border-destructive/40 bg-destructive/5 rounded-lg p-2 text-xs">
      <div className="font-mono text-destructive">{message}</div>
    </div>
  );
}
