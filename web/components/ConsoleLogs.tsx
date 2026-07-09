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
    let active = true;

    const loadLogs = async () => {
      try {
        const resp = await fetch(`/api/sandboxes/${sandboxId}/logs`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (active && data.logs) {
          setLogs(data.logs.split("\n"));
        }
      } catch {
        // ignore
      }
    };

    loadLogs();
    const interval = setInterval(loadLogs, 3000);

    return () => {
      active = false;
      clearInterval(interval);
    };
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
