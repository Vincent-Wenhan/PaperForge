"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useAppStore } from "@/lib/store";
import { MessageView } from "../MessageView";
import { ApprovalCard } from "../ApprovalCard";
import { Composer } from "../Composer";
import { EmptyState } from "../Skeleton";
import { ActivityTimeline, type ActivityItem } from "../ActivityTimeline";
import { projectToolActivities } from "@/lib/project-tools";
import { projectTurns } from "@/lib/project-turns";
import { taskStatusLabel } from "@/lib/presentation";

const BOTTOM_EDGE = 120;

export function ConversationPane() {
  const currentRun = useAppStore((s) => s.currentRun);
  const messages = useAppStore((s) => s.messages);
  const events = useAppStore((s) => s.events);
  const steps = useAppStore((s) => s.steps);
  const tasks = useAppStore((s) => s.tasks);
  const pendingApprovals = useAppStore((s) => s.pendingApprovals);
  const artifacts = useAppStore((s) => s.artifacts);
  const resolvePendingApproval = useAppStore((s) => s.resolvePendingApproval);

  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomSentinelRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);

  // Sentry observes the bottom sentinel; when it is visible the pane follows
  // new content, when the user scrolls up it stops and shows "Jump to latest".
  useEffect(() => {
    const root = scrollRef.current;
    const target = bottomSentinelRef.current;
    if (!root || !target) return;
    const observer = new IntersectionObserver(
      ([entry]) => setIsAtBottom(entry.isIntersecting),
      { root, rootMargin: `0px 0px ${BOTTOM_EDGE}px 0px` },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, []);

  // Reset "at bottom" detection whenever a new run is loaded.
  const runKey = currentRun?.id;
  useEffect(() => {
    setIsAtBottom(true);
  }, [runKey]);

  // Follow the stream only while pinned to bottom, and only on commit to avoid
  // fighting the user mid-scroll. rAF batches deltas within a frame.
  const lastScroll = useRef<number>(0);
  useLayoutEffect(() => {
    if (!isAtBottom) return;
    cancelAnimationFrame(lastScroll.current);
    lastScroll.current = requestAnimationFrame(() => {
      bottomSentinelRef.current?.scrollIntoView({ block: "end" });
    });
  }, [messages, steps, events, isAtBottom]);

  useEffect(() => () => cancelAnimationFrame(lastScroll.current), []);

  const scrollToLatest = () => {
    bottomSentinelRef.current?.scrollIntoView({ block: "end" });
    setIsAtBottom(true);
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  };

  if (!currentRun) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        Select a run or create a new one to get started.
      </div>
    );
  }

  const turns = projectTurns(tasks, messages, steps, pendingApprovals, artifacts);
  const orphanApprovals = turns.length === 0 ? pendingApprovals : [];
  const showEmpty = messages.length === 0 && events.length === 0;

  return (
    <section className="relative flex h-full min-h-0 flex-col overflow-hidden">
      <div
        ref={scrollRef}
        onWheel={() => {
          if (scrollRef.current) {
            const nearBottom =
              scrollRef.current.scrollHeight - scrollRef.current.scrollTop - scrollRef.current.clientHeight < BOTTOM_EDGE;
            setIsAtBottom(nearBottom);
          }
        }}
        className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain"
        data-testid="conversation-viewport"
      >
        <div className="mx-auto w-full max-w-[var(--conversation-max-width,900px)] px-4 pb-8 pt-6">
          {showEmpty && (
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
              {turn.task && (
                <div className="text-xs text-muted-foreground flex items-center gap-2">
                  <span data-testid="task-status">{taskStatusLabel(turn.status)}</span>
                  {turn.task.title && <span className="font-medium">{turn.task.title}</span>}
                </div>
              )}
              {turn.userMessage && (
                <MessageView
                  key={turn.userMessage.public_id ?? turn.userMessage.id ?? "user"}
                  id={turn.userMessage.id || turn.userMessage.public_id}
                  role="user"
                  content={turn.userMessage.content}
                  streaming={false}
                  failed={turn.userMessage.status === "failed"}
                  error={turn.userMessage.error ?? turn.userMessage.content}
                  toolCalls={turn.userMessage.tool_calls}
                  toolCallId={turn.userMessage.tool_call_id}
                />
              )}

              {(turn.steps.length > 0 || turn.assistantMessages.length > 0) && (
                <div className="pl-2">
                  {(() => {
                    const activities: ActivityItem[] = [
                      ...projectToolActivities(turn.assistantMessages).map((a) => ({ type: "tool" as const, activity: a })),
                      ...turn.steps.map((s) => ({ type: "step" as const, step: s })),
                      ...turn.approvals.map((ap) => ({ type: "approval" as const, approval: ap })),
                    ];
                    return <ActivityTimeline items={activities} />;
                  })()}
                  {turn.approvals.map((approval) => (
                    <ApprovalCard
                      key={approval.approval_id ?? approval.id}
                      approval={approval}
                      onResolved={(id: string, approved: boolean) => resolvePendingApproval(id, approved)}
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
                  {turn.artifacts.length > 0 && (
                    <div className="space-y-1">
                      {turn.artifacts.map((artifact) => (
                        <div
                          key={artifact.id}
                          className="text-xs font-mono text-muted-foreground flex items-center gap-2"
                        >
                          <span>📄 {artifact.type}</span>
                          <span>{artifact.path}</span>
                        </div>
                      ))}
                    </div>
                  )}
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
                  onResolved={(id: string, approved: boolean) => resolvePendingApproval(id, approved)}
                />
              ))}
            </div>
          )}

          <div ref={bottomSentinelRef} aria-hidden className="h-px" />
        </div>
      </div>

      {!isAtBottom && (
        <button
          onClick={scrollToLatest}
          className="absolute bottom-24 left-1/2 z-10 -translate-x-1/2 px-3 py-1 text-xs bg-foreground text-background rounded-full shadow"
        >
          ↓ Jump to latest
        </button>
      )}

      <Composer />
    </section>
  );
}
