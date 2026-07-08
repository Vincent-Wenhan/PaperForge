"use client";

import { useEffect, useRef, useState } from "react";
import { api, SSEClient } from "@/lib/api";
import { useAppStore } from "@/lib/store";

export function ChatPanel() {
  const currentRun = useAppStore((s) => s.currentRun);
  const messages = useAppStore((s) => s.messages);
  const addMessage = useAppStore((s) => s.addMessage);
  const addEvent = useAppStore((s) => s.addEvent);

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const sseRef = useRef<SSEClient | null>(null);

  // Load messages when currentRun changes
  useEffect(() => {
    if (!currentRun) return;
    api.listMessages(currentRun.id).then((msgs) => {
      useAppStore.setState({ messages: msgs });
    });

    // Connect SSE
    const sse = new SSEClient();
    sseRef.current = sse;
    sse.connect(currentRun.id);
    sse.on("message.delta", (data) => {
      addMessage({ role: "assistant", content: data.text || "" });
    });
    sse.on("tool.call", (data) => {
      addEvent({ id: "", type: "tool.call", data, run_id: currentRun.id });
    });
    sse.on("tool.result", (data) => {
      addEvent({ id: "", type: "tool.result", data, run_id: currentRun.id });
    });

    return () => {
      sse.disconnect();
      sseRef.current = null;
    };
  }, [currentRun, addMessage, addEvent]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || !currentRun) return;
    const content = input;
    setInput("");
    setSending(true);
    addMessage({ role: "user", content });
    try {
      await api.sendMessage(currentRun.id, content);
    } catch (err) {
      console.error(err);
    } finally {
      setSending(false);
    }
  };

  if (!currentRun) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        Select a run or create a new one to get started.
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col border-r border-border">
      <div className="p-3 border-b border-border">
        <h2 className="font-semibold">{currentRun.title}</h2>
        <p className="text-xs text-muted-foreground">{currentRun.id}</p>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`${
              msg.role === "user" ? "text-right" : "text-left"
            }`}
          >
            <div
              className={`inline-block px-3 py-2 rounded-lg max-w-[80%] ${
                msg.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted"
              }`}
            >
              <div className="text-sm whitespace-pre-wrap">
                {msg.content}
              </div>
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-3 border-t border-border flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !sending && handleSend()}
          placeholder="Send a message..."
          className="flex-1 px-3 py-2 border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary"
          disabled={sending}
        />
        <button
          onClick={handleSend}
          disabled={sending || !input.trim()}
          className="px-4 py-2 bg-primary text-primary-foreground rounded disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  );
}
