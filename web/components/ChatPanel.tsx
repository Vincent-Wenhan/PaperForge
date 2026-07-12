"use client";

import { useEffect, useRef, useState } from "react";
import { api, SSEClient } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { MessageView } from "./MessageView";
import { ToolCallCard } from "./ToolCallCard";
import { ApprovalCard } from "./ApprovalCard";
import { Composer } from "./Composer";

export function ChatPanel() {
  const currentRun = useAppStore((s) => s.currentRun);
  const messages = useAppStore((s) => s.messages);
  const events = useAppStore((s) => s.events);
  const pendingApprovals = useAppStore((s) => s.pendingApprovals);
  const artifacts = useAppStore((s) => s.artifacts);
  const addMessage = useAppStore((s) => s.addMessage);
  const appendAssistantDelta = useAppStore((s) => s.appendAssistantDelta);
  const finalizeStreamingAssistant = useAppStore((s) => s.finalizeStreamingAssistant);
  const addEvent = useAppStore((s) => s.addEvent);
  const setSandbox = useAppStore((s) => s.setSandbox);
  const addPendingApproval = useAppStore((s) => s.addPendingApproval);
  const resolvePendingApproval = useAppStore((s) => s.resolvePendingApproval);
  const setArtifacts = useAppStore((s) => s.setArtifacts);
  const setIsRunning = useAppStore((s) => s.setIsRunning);
  const appendMessageDelta = useAppStore((s) => s.appendMessageDelta);
  const completeMessage = useAppStore((s) => s.completeMessage);

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const sseRef = useRef<SSEClient | null>(null);

  useEffect(() => {
    if (!currentRun) return;

    // Single-shot hydration via /state endpoint (doc 1A.16).
    api.getRunState(currentRun.id).then((state) => {
      useAppStore.setState({
        messages: state.messages,
        artifacts: state.artifacts,
      });
      if (state.sandbox) {
        setSandbox(state.sandbox);
      }
      if (state.pending_approvals?.length) {
        state.pending_approvals.forEach((a) => addPendingApproval(a));
      }
    });

    const sse = new SSEClient();

    sse.on("message.started", (data: any) => {
      useAppStore.getState().upsertMessage({
        id: data.message_id,
        role: "assistant",
        content: "",
        streaming: true,
        status: "streaming",
      });
    });

    sse.on("message.delta", (data: any) => {
      if (data.message_id) {
        appendMessageDelta(data.message_id, data.delta || data.text || "");
      } else {
        appendAssistantDelta(data.text || data.delta || "");
      }
    });

    sse.on("message.completed", (data: any) => {
      if (data.message_id) {
        completeMessage(data.message_id, data.content || "");
      } else {
        finalizeStreamingAssistant();
      }
    });

    sse.on("message.failed", (data: any) => {
      if (data.message_id) {
        useAppStore.getState().failMessage(data.message_id, data.error || "Message failed");
      }
    });

    sse.on("run.finished", () => {
      finalizeStreamingAssistant();
      setIsRunning(false);
    });

    sse.on("run.error", () => {
      finalizeStreamingAssistant();
      setIsRunning(false);
    });

    sse.on("run.started", (data: any) => {
      addEvent({ id: "", type: "run.started", data, run_id: currentRun.id });
      setIsRunning(true);
    });

    sse.on("tool.call", (data: any) => {
      addEvent({ id: data.id || "", type: "tool.call", data, run_id: currentRun.id });
    });

    sse.on("tool.result", (data: any) => {
      addEvent({ id: data.call_id || "", type: "tool.result", data, run_id: currentRun.id });
    });

    sse.on("artifact.created", (data: any) => {
      addEvent({ id: data.artifact_id || "", type: "artifact.created", data, run_id: currentRun.id });
      if (data.artifact_id) {
        api.getArtifact(data.artifact_id).then((a) => useAppStore.getState().addArtifact(a)).catch(() => {});
      }
    });

    sse.on("approval.requested", (data: any) => {
      addEvent({ id: data.approval_id || "", type: "approval.requested", data, run_id: currentRun.id });
      addPendingApproval({
        approval_id: data.approval_id,
        tool: data.tool || data.tool_name || "",
        args: data.args || {},
        status: "pending",
      });
    });

    sse.on("approval.resolved", (data: any) => {
      addEvent({ id: data.approval_id || "", type: "approval.resolved", data, run_id: currentRun.id });
      resolvePendingApproval(data.approval_id, !!data.approved);
    });

    sse.on("sandbox.started", (data: any) => {
      setSandbox({
        id: data.sandbox_id,
        run_id: currentRun.id,
        container_id: data.container_id,
        preview_port: data.preview_port,
        status: "running",
      });
    });

    sse.on("sandbox.error", (data: any) => {
      addEvent({ id: "", type: "sandbox.error", data, run_id: currentRun.id });
    });

    sse.on("preview.ready", (data: any) => {
      addEvent({ id: "", type: "preview.ready", data, run_id: currentRun.id });
    });

    sse.connect(currentRun.id);
    sseRef.current = sse;

    return () => {
      sse.disconnect();
      sseRef.current = null;
    };
  }, [currentRun, addMessage, appendAssistantDelta, finalizeStreamingAssistant, addEvent, setSandbox, addPendingApproval, resolvePendingApproval, setArtifacts, setIsRunning, appendMessageDelta, completeMessage]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, events]);

  if (!currentRun) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        Select a run or create a new one to get started.
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col border-r border-border">
      <RunHeader
        title={currentRun.title}
        runId={currentRun.id}
        status={currentRun.status}
        phase={(currentRun.phase as string) || "init"}
        artifactCount={artifacts.length}
      />

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((msg, i) => (
          <MessageView
            key={i}
            role={msg.role}
            content={msg.content}
            toolCalls={msg.tool_calls}
            toolCallId={msg.tool_call_id}
          />
        ))}

        {pendingApprovals.length > 0 && (
          <div className="space-y-2">
            {pendingApprovals.map((approval) => (
              <ApprovalCard
                key={approval.approval_id}
                approval={approval}
                onResolved={(id, approved) => resolvePendingApproval(id, approved)}
              />
            ))}
          </div>
        )}

        {events.length > 0 && (
          <div className="space-y-2 mt-2">
            {events.slice(-20).map((event, i) => {
              if (event.type === "tool.call") {
                return (
                  <ToolCallCard
                    key={`ev-${i}`}
                    name={event.data.name || ""}
                    args={event.data.args || {}}
                  />
                );
              }
              return (
                <div
                  key={`ev-${i}`}
                  className="text-xs text-muted-foreground border-l-2 border-border pl-2"
                >
                  <span className="font-mono">{event.type}</span>
                </div>
              );
            })}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <Composer />
    </div>
  );
}

interface RunHeaderProps {
  title: string;
  runId: string;
  status: string;
  phase: string;
  artifactCount: number;
}

function RunHeader({ title, runId, status, phase, artifactCount }: RunHeaderProps) {
  return (
    <div className="p-3 border-b border-border">
      <h2 className="font-semibold">{title}</h2>
      <p className="text-xs text-muted-foreground">{runId}</p>
      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
        <span className="px-1.5 py-0.5 bg-muted rounded">{status}</span>
        <span className="px-1.5 py-0.5 bg-muted rounded">phase: {phase}</span>
        <span className="px-1.5 py-0.5 bg-muted rounded">
          {artifactCount} artifact{artifactCount === 1 ? "" : "s"}
        </span>
      </div>
    </div>
  );
}
