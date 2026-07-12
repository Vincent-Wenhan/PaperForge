"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { useToast } from "@/lib/toast";

const QUICK_ACTIONS: { id: string; label: string; description: string }[] = [
  { id: "productize", label: "Productize", description: "Productize the attached paper end-to-end." },
  { id: "alternatives", label: "Alternatives", description: "Generate alternative product candidates from this paper." },
  { id: "revise", label: "Revise PRD", description: "Revise the PRD based on the latest verification report." },
  { id: "fix", label: "Fix build", description: "Fix the failing build based on the latest verification report." },
  { id: "restart", label: "Restart preview", description: "Restart the preview sandbox." },
];

export function Composer() {
  const currentRun = useAppStore((s) => s.currentRun);
  const isRunning = useAppStore((s) => s.isRunning);
  const attachments = useAppStore((s) => s.attachments);
  const addMessage = useAppStore((s) => s.addMessage);
  const setIsRunning = useAppStore((s) => s.setIsRunning);
  const addAttachment = useAppStore((s) => s.addAttachment);
  const removeAttachment = useAppStore((s) => s.removeAttachment);
  const composerPrefill = useAppStore((s) => s.composerPrefill);
  const setComposerPrefill = useAppStore((s) => s.setComposerPrefill);
  const { toast } = useToast();

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Apply prefill when it changes (e.g., when user clicks "Ask PaperForge to fix")
  useEffect(() => {
    if (composerPrefill) {
      setInput(composerPrefill);
      setComposerPrefill("");
      textareaRef.current?.focus();
    }
  }, [composerPrefill, setComposerPrefill]);

  // Auto-resize textarea
  useEffect(() => {
    if (!textareaRef.current) return;
    const ta = textareaRef.current;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [input]);

  if (!currentRun) return null;

  const handleSend = async () => {
    if (!input.trim() || sending) return;
    const content = input;
    setInput("");
    setSending(true);
    addMessage({ role: "user", content });

    const paperIds = attachments
      .filter((att) => att.type === "paper" && att.paperId)
      .map((att) => att.paperId as string);

    try {
      await api.sendMessage(currentRun.id, content, paperIds);
      setIsRunning(true);
    } catch (err) {
      console.error(err);
      toast({
        title: "Failed to send message",
        description: err instanceof Error ? err.message : undefined,
        variant: "error",
      });
    } finally {
      setSending(false);
    }
  };

  const handleStop = async () => {
    try {
      await api.cancelRun(currentRun.id);
      setIsRunning(false);
      toast({ title: "Run cancelled", variant: "default" });
    } catch (err) {
      console.error(err);
    }
  };

  const handleQuickAction = (kind: string) => {
    const templates: Record<string, string> = {
      productize: "Productize the attached paper end-to-end.",
      alternatives: "Generate alternative product candidates from this paper.",
      revise: "Revise the PRD based on the latest verification report.",
      fix: "Fix the failing build based on the latest verification report.",
      restart: "Restart the preview sandbox.",
    };
    const text = templates[kind];
    if (!text) return;
    setInput(text);
    fileInputRef.current?.blur();
    textareaRef.current?.focus();
  };

  const handleAttach = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      addAttachment({
        id: file.name + Date.now(),
        type: "file",
        name: file.name,
        file,
      });
    }
    e.target.value = "";
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !sending) {
      e.preventDefault();
      handleSend();
    }
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border-t border-border p-3 bg-background">
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {attachments.map((att: any) => (
            <span
              key={att.id}
              className="px-2 py-1 text-xs bg-muted rounded flex items-center gap-1"
            >
              {att.name}
              <button
                onClick={() => removeAttachment(att.id)}
                className="hover:text-destructive"
                aria-label={`Remove ${att.name}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex items-center gap-1 mb-1 flex-wrap">
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action.id}
            onClick={() => handleQuickAction(action.id)}
            className="text-xs px-2 py-0.5 border border-border rounded hover:bg-accent"
            title={action.description}
          >
            {action.label}
          </button>
        ))}
      </div>
      <div className="flex items-end gap-2">
        <button
          onClick={() => fileInputRef.current?.click()}
          className="p-2 hover:bg-accent rounded text-sm"
          title="Attach file"
          aria-label="Attach file"
        >
          +
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={handleAttach}
        />
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask PaperForge to build or change something..."
          rows={2}
          className="flex-1 px-3 py-2 border border-border rounded resize-none focus:outline-none focus:ring-1 focus:ring-primary text-sm"
          disabled={sending}
        />
        {isRunning ? (
          <button
            onClick={handleStop}
            className="px-4 py-2 bg-destructive text-destructive-foreground rounded text-sm"
          >
            Stop
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={sending || !input.trim()}
            className="px-4 py-2 bg-primary text-primary-foreground rounded disabled:opacity-50 text-sm"
          >
            Send
          </button>
        )}
      </div>
    </div>
  );
}
