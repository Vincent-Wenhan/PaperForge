"use client";

import { memo } from "react";
import ReactMarkdown from "react-markdown";

interface MessageViewProps {
  id?: string;
  role: "user" | "assistant" | "tool";
  content: string;
  streaming?: boolean;
  toolCalls?: any[];
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

function MessageViewImpl({ role, content, streaming, toolCalls }: MessageViewProps) {
  const isUser = role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end" role="article" aria-label="User message">
        <div className="max-w-[80%] px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm whitespace-pre-wrap">
          {content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start" role="article" aria-label="Assistant message">
      <div className="max-w-[720px] w-full px-1 py-1">
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
                <span className="font-mono text-muted-foreground">→ {tc.name}</span>
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
