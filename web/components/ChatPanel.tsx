"use client";

import { useEffect, useRef, useState } from "react";
import { api, SSEClient } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { MessageView } from "./MessageView";
import { ToolCallCard } from "./ToolCallCard";
import { ApprovalCard } from "./ApprovalCard";

export function ChatPanel() {
  const currentRun = useAppStore((s) => s.currentRun);
  const messages = useAppStore((s) => s.messages);
  const events = useAppStore((s) => s.events);
  const pendingApprovals = useAppStore((s) => s.pendingApprovals);
  const addMessage = useAppStore((s) => s.addMessage);
  const addEvent = useAppStore((s) => s.addEvent);
  const setSandbox = useAppStore((s) => s.setSandbox);
  const addPendingApproval = useAppStore((s) => s.addPendingApproval);
  const resolvePendingApproval = useAppStore((s) => s.resolvePendingApproval);

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const sseRef = useRef<SSEClient | null>(null);

  useEffect(() => {
    if (!currentRun) return;

    api.listMessages(currentRun.id).then((msgs) => {
      useAppStore.setState({ messages: msgs });
    });

    const sse = new SSEClient();
    sseRef.current = sse;
    sse.connect(currentRun.id);

    sse.on("message.delta", (data) => {
      addMessage({ role: "assistant", content: data.text || "" });
    });

    sse.on("tool.call", (data) => {
      addEvent({ id: data.id || "", type: "tool.call", data, run_id: currentRun.id });
    });

    sse.on("tool.result", (data) => {
      addEvent({ id: data.call_id || "", type: "tool.result", data, run_id: currentRun.id });
    });

    sse.on("artifact.created", (data) => {
      addEvent({ id: data.artifact_id || "", type: "artifact.created", data, run_id: currentRun.id });
    });

    sse.on("approval.requested", (data) => {
      addEvent({ id: data.approval_id || "", type: "approval.requested", data, run_id: currentRun.id });
      addPendingApproval({
        approval_id: data.approval_id,
        tool: data.tool || data.tool_name || "",
        args: data.args || {},
        status: "pending",
      });
    });

    sse.on("approval.resolved", (data) => {
      addEvent({ id: data.approval_id || "", type: "approval.resolved", data, run_id: currentRun.id });
      resolvePendingApproval(data.approval_id, !!data.approved);
    });

    sse.on("sandbox.started", (data) => {
      setSandbox({
        id: data.sandbox_id,
        container_id: data.container_id,
        preview_port: data.preview_port,
        status: "running",
      });
    });

    sse.on("sandbox.error", (data) => {
      addEvent({ id: "", type: "sandbox.error", data, run_id: currentRun.id });
    });

    sse.on("preview.ready", (data) => {
      addEvent({ id: "", type: "preview.ready", data, run_id: currentRun.id });
    });

    sse.on("run.started", (data) => {
      addEvent({ id: "", type: "run.started", data, run_id: currentRun.id });
    });

    sse.on("run.finished", (data) => {
      addEvent({ id: "", type: "run.finished", data, run_id: currentRun.id });
    });

    sse.on("run.error", (data) => {
      addEvent({ id: "", type: "run.error", data, run_id: currentRun.id });
    });

    return () => {
      sse.disconnect();
      sseRef.current = null;
    };
  }, [currentRun, addMessage, addEvent, setSandbox, addPendingApproval, resolvePendingApproval]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, events]);

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
          <MessageView
            key={i}
            role={msg.role}
            content={msg.content}
            toolCalls={msg.tool_calls}
            toolCallId={msg.tool_call_id}
          />
        ))}

        {pendingApprovals.length > 0 && (
          <div className="space-y-2">
            {pendingApprovals.map((approval) => (
              <ApprovalCard
                key={approval.approval_id}
                approval={approval}
                onResolved={(id, approved) =>
                  resolvePendingApproval(id, approved)
                }
              />
            ))}
          </div>
        )}

        {events.length > 0 && (
          <div className="space-y-2 mt-2">
            {events.slice(-20).map((event, i) => {
              if (event.type === "tool.call") {
                return (
                  <ToolCallCard
                    key={`ev-${i}`}
                    name={event.data.name || ""}
                    args={event.data.args || {}}
                  />
                );
              }
              return (
                <div
                  key={`ev-${i}`}
                  className="text-xs text-muted-foreground border-l-2 border-border pl-2"
                >
                  <span className="font-mono">{event.type}</span>
                </div>
              );
            })}
          </div>
        )}

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
