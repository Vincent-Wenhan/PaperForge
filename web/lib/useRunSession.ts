"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api, SSEClient } from "./api";
import { applyRunEvent } from "./run-events";
import { useAppStore } from "./store";

export function useRunSession(runId: string | null | undefined) {
  const [loading, setLoading] = useState(Boolean(runId));
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const hydrate = useCallback(async () => {
    if (!runId) return 0;
    const state = await api.getRunState(runId);
    const pending = state.pending_approvals || state.approvals.filter((item) => item.status === "pending");
    useAppStore.setState({
      currentRun: state.run,
      messages: state.messages.map((message) => ({
        ...message,
        id: message.id || message.public_id,
      })),
      artifacts: state.artifacts,
      sandbox: state.sandbox,
      pendingApprovals: pending,
      tasks: state.tasks || [],
      steps: state.steps || [],
      sandboxLogs: [],
      lastSeq: state.event_cursor,
      isRunning: state.run.status === "running",
      preview: state.preview || null,
      sessionError: null,
    });
    return state.event_cursor;
  }, [runId]);

  useEffect(() => {
    if (!runId) {
      setLoading(false);
      setError(null);
      useAppStore.getState().setConnection("offline");
      return;
    }

    let active = true;
    const sse = new SSEClient();

    // Clear the previous run's workspace immediately. Hydration will replace
    // it with the new snapshot once the request completes.
    useAppStore.getState().setCurrentRun(null);
    // New runs (no app/sandbox) still surface the Preview panel as an available
    // destination — the workbench is closable but not hidden by default.
    useAppStore.getState().setWorkbenchMode("open");

    const connect = async () => {
      setLoading(true);
      setError(null);
      useAppStore.getState().setConnection("connecting");
      try {
        const cursor = await hydrate();
        if (!active) return;
        // Real SSE connection state feeds the header indicator. EventSource
        // auto-reconnects and re-requests from after_seq on retry, so a
        // transient drop resumes from the last durable cursor without resync.
        sse.onConnectionState((state) => {
          useAppStore.getState().setConnection(state);
        });
        // Single onmessage: semantic type rides in the JSON envelope.
        sse.onMessage((event) => {
          const result = applyRunEvent(event, runId);
          // Only a real seq gap rehydrates; unknown types are ignored.
          if (result === "gap") {
            void hydrate().catch((err) => {
              if (active) {
                const apiError = err instanceof ApiError
                  ? err
                  : new ApiError(0, err instanceof Error ? err.message : String(err));
                setError(apiError);
                useAppStore.getState().setSessionError(apiError.message);
              }
            });
          }
        });
        sse.connect(runId, cursor);
      } catch (err) {
        if (!active) return;
        const apiError = err instanceof ApiError
          ? err
          : new ApiError(0, err instanceof Error ? err.message : String(err));
        setError(apiError);
        useAppStore.getState().setSessionError(apiError.message);
      } finally {
        if (active) setLoading(false);
      }
    };

    void connect();
    return () => {
      active = false;
      sse.disconnect();
      useAppStore.getState().setConnection("offline");
    };
  }, [runId, hydrate, reloadKey]);

  return {
    loading,
    error,
    refresh: hydrate,
    retry: () => setReloadKey((value) => value + 1),
  };
}
