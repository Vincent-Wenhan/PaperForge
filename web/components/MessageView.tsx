"use client";

import { memo } from "react";
import ReactMarkdown from "react-markdown";

interface MessageViewProps {
  id?: string;
  role: "user" | "assistant" | "tool";
  content: string;
  streaming?: boolean;
  failed?: boolean;
  error?: string;
  toolCalls?: unknown[];
  toolCallId?: string;
}

function StreamingCaret() {
  return (
    <span
      aria-hidden
      className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-current align-middle"
    />
  );
}

function MessageViewImpl({ role, content, streaming, failed, error, toolCalls }: MessageViewProps) {
  const isUser = role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end" role="article" aria-label="User message">
        <div
          className={`max-w-[80%] px-3 py-2 rounded-lg text-sm whitespace-pre-wrap ${
            failed
              ? "bg-destructive/15 text-destructive border border-destructive/30"
              : "bg-primary text-primary-foreground"
          }`}
          data-testid={failed ? "user-message-failed" : "user-message"}
        >
          {content}
          {failed && error && (
            <div className="mt-1 text-[11px] opacity-90">Not sent: {error}</div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start" role="article" aria-label="Assistant message">
      <div
        className="max-w-[720px] w-full px-1 py-1"
        data-testid={streaming ? "assistant-message-current" : "assistant-message"}
        data-streaming={streaming ? "true" : "false"}
      >
        <div className="text-sm prose prose-sm max-w-none">
          <ReactMarkdown>{content || ""}</ReactMarkdown>
          {streaming && <StreamingCaret />}
        </div>
        {toolCalls && toolCalls.length > 0 && (
          <div className="mt-2 space-y-1">
            {toolCalls.map((tc, i) => (
              <div
                key={i}
                className="text-xs bg-muted rounded p-1.5 border border-border"
              >
                <span className="font-mono text-muted-foreground">→ {String((tc as { name?: unknown })?.name ?? tc)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export const MessageView = memo(
  MessageViewImpl,
  (prev, next) =>
    prev.id === next.id &&
    prev.content === next.content &&
    prev.role === next.role &&
    prev.streaming === next.streaming,
);
