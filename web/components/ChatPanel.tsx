"use client";

import { useEffect, useRef } from "react";
import { useAppStore } from "@/lib/store";
import { MessageView } from "./MessageView";
import { ApprovalCard } from "./ApprovalCard";
import { StepList } from "./StepList";
import { Composer } from "./Composer";
import { EmptyState } from "./Skeleton";
import { projectTurns } from "@/lib/project-turns";

export function ChatPanel() {
  const currentRun = useAppStore((s) => s.currentRun);
  const messages = useAppStore((s) => s.messages);
  const events = useAppStore((s) => s.events);
  const steps = useAppStore((s) => s.steps);
  const tasks = useAppStore((s) => s.tasks);
  const pendingApprovals = useAppStore((s) => s.pendingApprovals);
  const artifacts = useAppStore((s) => s.artifacts);
  const resolvePendingApproval = useAppStore((s) => s.resolvePendingApproval);

  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedToBottom = useRef(true);
  const jumpRef = useRef({ visible: false });

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 96;
    pinnedToBottom.current = nearBottom;
    jumpRef.current.visible = !nearBottom;
  };

  const jumpToLatest = () => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
      pinnedToBottom.current = true;
      jumpRef.current.visible = false;
    }
  };

  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinnedToBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, events, steps]);

  if (!currentRun) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        Select a run or create a new one to get started.
      </div>
    );
  }

  const turns = projectTurns(
    tasks,
    messages,
    steps,
    pendingApprovals,
    artifacts,
  );

  // Pending approvals not yet attributed to a task (pre-16 data) still render.
  const orphanApprovals = turns.length === 0 ? pendingApprovals : [];

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
        ref={scrollRef}
        onScroll={onScroll}
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

        {turns.map((turn) => (
          <section
            key={turn.id}
            data-task-id={turn.id}
            className="space-y-3 py-2 border-b border-border/60 last:border-0"
          >
            {turn.userMessage && (
              <MessageView
                key={turn.userMessage.public_id ?? turn.userMessage.id ?? "user"}
                id={turn.userMessage.id || turn.userMessage.public_id}
                role="user"
                content={turn.userMessage.content}
                streaming={false}
                toolCalls={turn.userMessage.tool_calls}
                toolCallId={turn.userMessage.tool_call_id}
              />
            )}

            {(turn.steps.length > 0 || turn.assistantMessages.length > 0) && (
              <div className="pl-2">
                <StepList steps={turn.steps} />
                {turn.approvals.map((approval) => (
                  <ApprovalCard
                    key={approval.approval_id ?? approval.id}
                    approval={approval}
                    onResolved={(id, approved) => resolvePendingApproval(id, approved)}
                  />
                ))}
                {turn.assistantMessages.map((msg) => (
                  <MessageView
                    key={msg.public_id ?? msg.id ?? `${msg.role}-${msg.content}`}
                    id={msg.id || msg.public_id}
                    role={msg.role}
                    content={msg.content}
                    streaming={msg.streaming}
                    toolCalls={msg.tool_calls}
                    toolCallId={msg.tool_call_id}
                  />
                ))}
              </div>
            )}
          </section>
        ))}

        {orphanApprovals.length > 0 && (
          <div className="space-y-2">
            {orphanApprovals.map((approval) => (
              <ApprovalCard
                key={approval.approval_id}
                approval={approval}
                onResolved={(id, approved) => resolvePendingApproval(id, approved)}
              />
            ))}
          </div>
        )}

        <div className="h-px" />
      </div>

      {jumpRef.current.visible && (
        <button
          onClick={jumpToLatest}
          className="absolute bottom-24 left-1/2 -translate-x-1/2 px-3 py-1 text-xs bg-foreground text-background rounded-full shadow"
        >
          ↓ Jump to latest
        </button>
      )}

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
