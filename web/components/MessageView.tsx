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

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`inline-block px-3 py-2 rounded-lg max-w-[80%] ${
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted"
        }`}
      >
        {isUser ? (
          <div className="text-sm whitespace-pre-wrap">{content}</div>
        ) : (
          <div className="text-sm prose prose-sm max-w-none">
            <ReactMarkdown>{content || ""}</ReactMarkdown>
          </div>
        )}
        {toolCalls && toolCalls.length > 0 && (
          <div className="mt-2 space-y-1">
            {toolCalls.map((tc, i) => (
              <div
                key={i}
                className="text-xs bg-primary-foreground/10 rounded p-1"
              >
                → {tc.name}({JSON.stringify(tc.args)})
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
