"use client";

import { useState } from "react";

interface ToolCallCardProps {
  name: string;
  args: any;
  result?: any;
  callId?: string;
}

export function ToolCallCard({ name, args, result, callId }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="my-2 border border-border rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-2 bg-muted/50 flex items-center justify-between text-sm hover:bg-muted"
      >
        <span className="font-mono">{name}()</span>
        <span className="text-xs text-muted-foreground">
          {expanded ? "▼" : "▶"}
        </span>
      </button>
      {expanded && (
        <div className="p-3 space-y-2">
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
                {typeof result === "string" ? result : JSON.stringify(result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
