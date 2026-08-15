"use client";

import { memo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        } catch {
          /* clipboard may be unavailable in some contexts */
        }
      }}
      className="px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground rounded hover:bg-accent"
      aria-label="Copy code"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

// Code-block renderer with a copy button (doc 7.4). Inline code is left as-is.
function CodeBlock({ className, children, ...props }: { className?: string; children?: React.ReactNode } & Record<string, unknown>) {
  const match = /language-(\w+)/.exec(className || "");
  const text = Array.isArray(children) ? String(children.join("")) : String(children ?? "");
  const isBlock = Boolean(match) || text.includes("\n");
  if (!isBlock) {
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  }
  const code = text.replace(/\n$/, "");
  return (
    <div className="my-2 overflow-hidden rounded-lg border border-border bg-muted/30">
      <div className="flex items-center justify-between border-b border-border bg-muted/40 px-3 py-1.5">
        <span className="text-xs text-muted-foreground">{match?.[1] ?? "code"}</span>
        <CopyButton value={code} />
      </div>
      <pre className="overflow-x-auto p-3 text-xs">
        <code className={className}>{code}</code>
      </pre>
    </div>
  );
}

const MarkdownComponents: Components = {
  code: CodeBlock as any,
};

interface MarkdownProps {
  content: string;
}

function MarkdownImpl({ content }: MarkdownProps) {
  return (
    <div className="text-sm prose prose-sm max-w-none">
      <ReactMarkdown components={MarkdownComponents}>{content || ""}</ReactMarkdown>
    </div>
  );
}

export const Markdown = memo(MarkdownImpl);
