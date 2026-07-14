"use client";

import { useEffect, useRef } from "react";
import { useAppStore } from "@/lib/store";
import { MessageView } from "./MessageView";
import { ToolCallCard } from "./ToolCallCard";
import { ApprovalCard } from "./ApprovalCard";
import { AgentActivity } from "./AgentActivity";
import { Composer } from "./Composer";
import { EmptyState } from "./Skeleton";

export function ChatPanel() {
  const currentRun = useAppStore((s) => s.currentRun);
  const messages = useAppStore((s) => s.messages);
  const events = useAppStore((s) => s.events);
  const pendingApprovals = useAppStore((s) => s.pendingApprovals);
  const artifacts = useAppStore((s) => s.artifacts);
  const resolvePendingApproval = useAppStore((s) => s.resolvePendingApproval);

  const messagesEndRef = useRef<HTMLDivElement>(null);

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

      <div
        className="flex-1 overflow-y-auto p-4 space-y-3"
        role="log"
        aria-live="polite"
        aria-label="Conversation messages"
      >
        {messages.length === 0 && events.length === 0 && (
          <EmptyState
            icon="💬"
            title="Start a conversation"
            description="Send a message below to start working with PaperForge. Ask a question or request to productize a paper."
          />
        )}
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
            <AgentActivity events={events.slice(-20)} />
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
