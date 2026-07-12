"use client";

import ReactMarkdown from "react-markdown";

interface MessageViewProps {
  role: "user" | "assistant" | "tool";
  content: string;
  toolCalls?: any[];
  toolCallId?: string;
}

export function MessageView({ role, content, toolCalls }: MessageViewProps) {
  const isUser = role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm whitespace-pre-wrap">
          {content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[720px] w-full px-1 py-1">
        <div className="text-sm prose prose-sm max-w-none">
          <ReactMarkdown>{content || ""}</ReactMarkdown>
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
