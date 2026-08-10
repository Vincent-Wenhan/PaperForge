"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { useToast } from "@/lib/toast";

const SLASH_TEMPLATES: Record<string, string> = {
  productize: "Productize the attached paper end-to-end.",
  alternatives: "Generate alternative product candidates from this paper.",
  "revise-prd": "Revise the PRD based on the latest verification report.",
  fix: "Fix the failing build based on the latest verification report.",
  "restart-preview": "Restart the preview sandbox.",
};

function isSlashTemplate(text: string): string | null {
  const key = text.slice(1).trim();
  if (text.startsWith("/") && SLASH_TEMPLATES[key]) return SLASH_TEMPLATES[key];
  return null;
}

export function Composer() {
  const currentRun = useAppStore((s) => s.currentRun);
  const isRunning = useAppStore((s) => s.isRunning);
  const attachments = useAppStore((s) => s.attachments);
  const addMessage = useAppStore((s) => s.addMessage);
  const removeMessage = useAppStore((s) => s.removeMessage);
  const clearAttachments = useAppStore((s) => s.clearAttachments);
  const setIsRunning = useAppStore((s) => s.setIsRunning);
  const addAttachment = useAppStore((s) => s.addAttachment);
  const removeAttachment = useAppStore((s) => s.removeAttachment);
  const composerPrefill = useAppStore((s) => s.composerPrefill);
  const setComposerPrefill = useAppStore((s) => s.setComposerPrefill);
  const { toast } = useToast();

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const submitLock = useRef(false);

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

  type SendMode = "start" | "queue" | "interrupt";

  const resolvePaperIds = async (): Promise<string[]> => {
    const ids: string[] = [];
    for (const attachment of attachments) {
      if (attachment.type === "paper" && attachment.paperId) {
        ids.push(attachment.paperId);
        continue;
      }
      if (attachment.file) {
        if (attachment.file.type !== "application/pdf") {
          throw new Error("PaperForge currently supports PDF attachments only");
        }
        setUploading(true);
        try {
          const uploaded = await api.uploadPaper(attachment.file);
          ids.push(uploaded.paper_id);
        } finally {
          setUploading(false);
        }
      }
    }
    return ids;
  };

  const submitMessage = async (mode: SendMode) => {
    const raw = input.trim();
    if (!raw || sending || submitLock.current) return;
    const content = isSlashTemplate(raw) ?? raw;
    submitLock.current = true;
    setSending(true);

    const optimisticId =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `msg_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;

    addMessage({
      id: optimisticId,
      public_id: optimisticId,
      role: "user",
      content,
      streaming: false,
      status: "completed",
    });

    try {
      const paperIds = await resolvePaperIds();
      await api.sendMessage(currentRun.id, content, paperIds, optimisticId, mode);
      clearAttachments();
      setInput("");
      setIsRunning(true);
    } catch (error) {
      removeMessage(optimisticId);
      setInput(content);
      toast({
        title: "Message was not sent",
        description: error instanceof Error ? error.message : String(error),
        variant: "error",
      });
    } finally {
      submitLock.current = false;
      setSending(false);
    }
  };

  const handleStop = async () => {
    try {
      await api.cancelRun(currentRun.id);
      setIsRunning(false);
      toast({ title: "Run cancelled", variant: "default" });
    } catch (err) {
      toast({ title: "Cancel failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
    }
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
    if (e.nativeEvent.isComposing) return;
    if (e.key !== "Enter") return;

    const commandEnter = e.metaKey || e.ctrlKey;
    const plainEnter = !e.shiftKey && !e.metaKey && !e.ctrlKey;
    if (!commandEnter && !plainEnter) return;
    if (sending) return;

    e.preventDefault();
    void submitMessage(useAppStore.getState().isRunning ? "queue" : "start");
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
      <div className="flex items-end gap-2">
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={sending || uploading}
          className="p-2 hover:bg-accent rounded text-sm disabled:opacity-50"
          title="Attach PDF"
          aria-label="Attach PDF"
        >
          +
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={handleAttach}
        />
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            isRunning
              ? "Add a follow-up... (queued after the current task)"
              : "Ask PaperForge to build or change something..."
          }
          rows={2}
          className="flex-1 px-3 py-2 border border-border rounded resize-none focus:outline-none focus:ring-1 focus:ring-primary text-sm disabled:opacity-50"
          disabled={sending || uploading}
        />
        <div className="flex gap-2">
          {isRunning && (
            <>
              <button
                onClick={handleStop}
                className="px-3 py-2 bg-secondary text-secondary-foreground rounded text-sm"
                title="Stop the current task"
              >
                ■
              </button>
              {input.trim() && (
                <button
                  onClick={() => submitMessage("interrupt")}
                  className="px-3 py-2 bg-destructive text-destructive-foreground rounded text-sm"
                  title="Interrupt the current task and send this message"
                >
                  ↻ Interrupt
                </button>
              )}
            </>
          )}
          <button
            onClick={() => submitMessage(isRunning ? "queue" : "start")}
            disabled={sending || uploading || !input.trim()}
            className="px-4 py-2 bg-primary text-primary-foreground rounded disabled:opacity-50 text-sm"
          >
            {uploading
              ? "Uploading…"
              : isRunning
                ? "Queue ↑"
                : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
