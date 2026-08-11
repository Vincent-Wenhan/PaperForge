"use client";

import { useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { EmptyState } from "../Skeleton";
import { useToast } from "@/lib/toast";

export function PreviewFrame({ sandbox, preview }: { sandbox?: any; preview?: any }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [viewport, setViewport] = useState<"desktop" | "tablet" | "mobile">("desktop");
  const { toast } = useToast();

  // Prefer a server-returned preview origin so production can point the
  // iframe at an isolated origin. Fall back to the proxied API URL.
  const previewSrc =
    preview?.preview_url
    ?? sandbox?.preview_url
    ?? (sandbox?.id ? api.getPreviewUrl(sandbox.id) : null);

  const handleRefresh = () => {
    if (iframeRef.current) {
      iframeRef.current.src = iframeRef.current.src;
    }
  };

  const handleOpenNewTab = () => {
    if (sandbox?.id) {
      window.open(api.getPreviewUrl(sandbox.id), "_blank");
    }
  };

  const handleRestart = async () => {
    if (!sandbox?.id) return;
    try {
      const next = await api.restartSandbox(sandbox.id);
      if (next) {
        useAppStore.getState().setSandbox(next);
      }
      useAppStore.getState().setPreview({
        status: "starting",
        sandbox_id: next?.id || sandbox.id,
      });
      toast({ title: "Preview restarted", variant: "success" });
    } catch (err) {
      useAppStore.getState().setPreview({
        status: "degraded",
        sandbox_id: sandbox.id,
        error: err instanceof Error ? err.message : "Failed to restart sandbox",
      });
      toast({ title: "Restart failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
    }
  };

  const handleStop = async () => {
    if (!sandbox?.id) return;
    try {
      await api.stopSandbox(sandbox.id);
      useAppStore.getState().setSandbox({ ...sandbox, status: "stopped" });
      useAppStore.getState().setPreview({ status: "stopped", sandbox_id: sandbox.id });
      toast({ title: "Preview stopped", variant: "default" });
    } catch (err) {
      useAppStore.getState().setPreview({
        status: "degraded",
        sandbox_id: sandbox.id,
        error: err instanceof Error ? err.message : "Failed to stop sandbox",
      });
      toast({ title: "Stop failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
    }
  };

  const viewportWidth = {
    desktop: "100%",
    tablet: "768px",
    mobile: "375px",
  }[viewport];

  if (!sandbox?.id) {
    if (preview?.status === "degraded" || preview?.status === "error") {
      return (
        <EmptyState
          icon="⚠️"
          title="Preview unavailable"
          description={preview.error || "The preview environment is degraded. Restart the sandbox to try again."}
        />
      );
    }
    return (
      <EmptyState
        icon="🚀"
        title="No live preview yet"
        description="Once the orchestrator reaches the preview phase, the live app will appear here."
      />
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-background">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">Sandbox: {sandbox.status || "unknown"}</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="flex items-center gap-0.5 mr-2" role="group" aria-label="Viewport">
            {(["desktop", "tablet", "mobile"] as const).map((vp) => (
              <button
                key={vp}
                onClick={() => setViewport(vp)}
                className={`px-2 py-1 text-xs rounded ${
                  viewport === vp ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                }`}
                title={vp}
                aria-pressed={viewport === vp}
              >
                {vp === "desktop" ? "🖥" : vp === "tablet" ? "📱" : "📲"}
              </button>
            ))}
          </div>
          <button onClick={handleRefresh} className="px-2 py-1 text-xs rounded hover:bg-muted" title="Refresh">↻</button>
          <button onClick={handleRestart} className="px-2 py-1 text-xs rounded hover:bg-muted" title="Restart sandbox">⟳</button>
          <button onClick={handleOpenNewTab} className="px-2 py-1 text-xs rounded hover:bg-muted" title="Open in new tab">↗</button>
          <button onClick={handleStop} className="px-2 py-1 text-xs rounded hover:bg-muted text-destructive" title="Stop sandbox">■</button>
        </div>
      </div>

      <div className="flex-1 overflow-hidden flex justify-center bg-muted/20">
        <iframe
          ref={iframeRef}
          src={previewSrc ?? ""}
          className="border-0 transition-all"
          style={{ width: viewportWidth, height: "100%" }}
          title="Preview"
          sandbox="allow-scripts allow-forms allow-modals allow-popups"
          referrerPolicy="no-referrer"
        />
      </div>
    </div>
  );
}
