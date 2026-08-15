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
  type SendMode = "start" | "queue" | "interrupt";
  const currentRun = useAppStore((s) => s.currentRun);
  const isRunning = useAppStore((s) => s.isRunning);
  const attachments = useAppStore((s) => s.attachments);
  const addMessage = useAppStore((s) => s.addMessage);
  const reconcileMessage = useAppStore((s) => s.reconcileMessage);
  const upsertTask = useAppStore((s) => s.upsertTask);
  const setLastSeq = useAppStore((s) => s.setLastSeq);
  const failMessage = useAppStore((s) => s.failMessage);
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
  const [failedSend, setFailedSend] = useState<{
    optimisticId: string;
    content: string;
    paperIds: string[];
    mode: SendMode;
  } | null>(null);
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

  const send = async (
    mode: SendMode,
    opts: { content: string; paperIds?: string[]; optimisticId: string; preserveAttachments?: boolean },
  ) => {
    const raw = opts.content.trim();
    if (!raw || sending || submitLock.current) return;
    const content = isSlashTemplate(raw) ?? raw;
    submitLock.current = true;
    setSending(true);

    const optimisticId = opts.optimisticId;
    const sendPaperIds = opts.paperIds ?? [];

    // Retry reuses the original optimistic id so the idempotency key (public_id)
    // is stable and the same user message is not duplicated server-side. Only
    // synth-add the message if it isn't already present (e.g. a prior failed
    // attempt left it in the store with the same id).
    const alreadyAdded = useAppStore
      .getState()
      .messages.some((m) => m.id === optimisticId || m.public_id === optimisticId);
    if (!alreadyAdded) {
      addMessage({
        id: optimisticId,
        public_id: optimisticId,
        role: "user",
        content,
        streaming: false,
        status: "sending",
      });
    }

    try {
      const paperIds = sendPaperIds.length > 0 ? sendPaperIds : await resolvePaperIds();
      const result = await api.sendMessage(currentRun.id, content, paperIds, optimisticId, mode);
      // Reconcile the optimistic user message with the server's authoritative
      // row so its id/public_id/task match, and adopt the returned Task +
      // SSE cursor so the reply streams in without a page refresh.
      if (result?.message?.id) {
        reconcileMessage({
          id: result.message.id,
          public_id: result.message.public_id || result.message.id,
          task_id: result.task_id || result.message.task_id,
          content: result.message.content ?? content,
          status: result.message.status === "failed"
            ? "failed"
            : result.message.status === "streaming"
              ? "streaming"
              : "completed",
        });
      }
      if (result?.task) {
        upsertTask({
          id: result.task.id ?? result.task.task_id,
          task_id: result.task.task_id ?? result.task.id,
          run_id: result.task.run_id ?? currentRun.id,
          title: result.task.title ?? null,
          goal: result.task.goal ?? null,
          status: result.task.status ?? "queued",
          phase: result.task.phase,
          created_at: result.task.created_at,
          updated_at: result.task.updated_at,
          completed_at: result.task.completed_at ?? null,
        });
      }
      if (typeof result?.event_cursor === "number" && result.event_cursor > 0) {
        setLastSeq(result.event_cursor);
      }
      setFailedSend(null);
      clearAttachments();
      setInput("");
      setIsRunning(true);
    } catch (error) {
      // Keep the user message (as failed) and remember everything needed for
      // a same-key retry. Attachments are preserved in the store.
      failMessage(optimisticId, error instanceof Error ? error.message : String(error));
      setFailedSend({ optimisticId, content, paperIds: sendPaperIds, mode });
      if (!opts.preserveAttachments) setInput(content);
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

  const submitMessage = (mode: SendMode) => {
    const raw = input.trim();
    if (!raw || sending || submitLock.current) return;
    const optimisticId =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `msg_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
    setInput("");
    void send(mode, { content: raw, optimisticId });
  };

  const retryFailed = () => {
    if (!failedSend) return;
    const { optimisticId, content, paperIds, mode } = failedSend;
    void send(mode, {
      content,
      paperIds,
      optimisticId,
      preserveAttachments: true,
    });
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
    <div className="shrink-0 border-t border-border bg-background/95 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur">
      {failedSend && (
        <div
          className="flex items-center justify-between gap-2 mb-2 mx-auto max-w-[var(--composer-max-width,820px)] px-3 py-2 text-xs bg-destructive/10 border border-destructive/30 rounded"
          data-testid="send-failed-banner"
        >
          <span className="text-destructive">
            Message failed to send.
            <span className="block text-muted-foreground text-[11px]">
              You can retry without losing your message or attachments.
            </span>
          </span>
          <button
            onClick={retryFailed}
            disabled={sending}
            className="px-2 py-1 rounded border border-border bg-background hover:bg-accent text-destructive"
            data-testid="send-retry"
          >
            Retry
          </button>
        </div>
      )}
      <div className="mx-auto max-w-[var(--composer-max-width,820px)] rounded-2xl border border-border bg-background shadow-sm">
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-1 px-3 pt-2">
            {attachments.map((att) => (
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
        <div className="flex items-end gap-2 p-2">
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
            className="flex-1 px-3 py-2 bg-transparent border border-border rounded resize-none focus:outline-none focus:ring-1 focus:ring-primary text-sm disabled:opacity-50"
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
    </div>
  );
}
