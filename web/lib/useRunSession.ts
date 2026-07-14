"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, api, SSEClient } from "./api";
import { applyRunEvent } from "./run-events";
import { useAppStore } from "./store";

const EVENT_TYPES = [
  "message.started",
  "message.delta",
  "message.completed",
  "message.failed",
  "tool.call",
  "tool.result",
  "run.started",
  "run.finished",
  "run.error",
  "run.status.changed",
  "run.updated",
  "task.phase.changed",
  "approval.requested",
  "approval.resolved",
  "artifact.created",
  "artifact.updated",
  "sandbox.started",
  "sandbox.error",
  "preview.ready",
  "stream.gap",
];

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
      lastSeq: state.event_cursor,
      isRunning: state.run.status === "running",
      preview: state.preview || null,
      sessionError: null,
    } as any);
    return state.event_cursor;
  }, [runId]);

  useEffect(() => {
    if (!runId) {
      setLoading(false);
      setError(null);
      return;
    }

    let active = true;
    const sse = new SSEClient();

    // Clear the previous run's workspace immediately. Hydration will replace
    // it with the new snapshot once the request completes.
    useAppStore.getState().setCurrentRun(null);

    const connect = async () => {
      setLoading(true);
      setError(null);
      try {
        const cursor = await hydrate();
        if (!active) return;
        for (const eventType of EVENT_TYPES) {
          sse.on(eventType, (_payload, event) => {
            const result = applyRunEvent(event, runId);
            if (result === "gap" || result === "unknown") {
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
        }
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
    };
  }, [runId, hydrate, reloadKey]);

  return {
    loading,
    error,
    refresh: hydrate,
    retry: () => setReloadKey((value) => value + 1),
  };
}
