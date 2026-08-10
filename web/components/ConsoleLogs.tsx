"use client";

import { useEffect } from "react";
import { useAppStore } from "@/lib/store";

interface ConsoleLogsProps {
  sandboxId?: string;
}

export function ConsoleLogs({ sandboxId }: ConsoleLogsProps) {
  const logs = useAppStore((s) => s.sandboxLogs);

  // Reset buffered log deltas when the sandbox changes.
  useEffect(() => {
    useAppStore.getState().clearSandboxLogs();
  }, [sandboxId]);

  if (!sandboxId) {
    return (
      <div
        className="h-full flex items-center justify-center text-muted-foreground text-sm p-4"
        role="status"
      >
        Start a sandbox to view live logs.
      </div>
    );
  }

  return (
    <div
      className="h-full overflow-y-auto p-2 font-mono text-xs"
      role="log"
      aria-live="polite"
      aria-label="Sandbox logs"
    >
      {logs.length === 0 ? (
        <div className="text-muted-foreground">No logs yet</div>
      ) : (
        logs.map((line, i) => <div key={i}>{line.text}</div>)
      )}
    </div>
  );
}

