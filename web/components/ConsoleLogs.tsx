"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface ConsoleLogsProps {
  sandboxId?: string;
}

export function ConsoleLogs({ sandboxId }: ConsoleLogsProps) {
  const [logs, setLogs] = useState<string[]>([]);

  useEffect(() => {
    if (!sandboxId) return;
    // For now, logs are static; in future, stream via SSE
    setLogs([`Sandbox: ${sandboxId}`, "Waiting for dev server to start..."]);
  }, [sandboxId]);

  return (
    <div className="h-full overflow-y-auto p-2 font-mono text-xs">
      {logs.length === 0 ? (
        <div className="text-muted-foreground">No logs yet</div>
      ) : (
        logs.map((line, i) => <div key={i}>{line}</div>)
      )}
    </div>
  );
}
