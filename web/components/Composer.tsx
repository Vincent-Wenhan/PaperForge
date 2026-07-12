"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";

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

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Apply prefill when it changes (e.g., when user clicks "Ask PaperForge to fix")
  useEffect(() => {
    if (composerPrefill) {
      setInput(composerPrefill);
      setComposerPrefill("");
    }
  }, [composerPrefill, setComposerPrefill]);

  if (!currentRun) return null;

  const handleSend = async () => {
    if (!input.trim() || sending) return;
    const content = input;
    setInput("");
    setSending(true);
    addMessage({ role: "user", content });
    try {
      await api.sendMessage(currentRun.id, content);
      setIsRunning(true);
    } catch (err) {
      console.error(err);
    } finally {
      setSending(false);
    }
  };

  const handleStop = async () => {
    try {
      await api.cancelRun(currentRun.id);
      setIsRunning(false);
    } catch (err) {
      console.error(err);
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
          className="p-2 hover:bg-accent rounded text-sm"
          title="Attach file"
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
