"use client";

import { useEffect, useState } from "react";
import { useTheme } from "@/lib/useTheme";
import { useToast } from "@/lib/toast";
import type { Run } from "@/lib/store";

interface GlobalHeaderProps {
  onToggleCommandPalette?: () => void;
  onToggleSidebar?: () => void;
  currentRun?: Run | null;
  connectionStatus?: "connected" | "connecting" | "error";
}

export function GlobalHeader({
  onToggleCommandPalette,
  onToggleSidebar,
  currentRun,
  connectionStatus = "connected",
}: GlobalHeaderProps) {
  const { theme, toggleTheme } = useTheme();
  const { toast } = useToast();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Ponytail: inline keyboard shortcut registration — no library needed.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Don't trigger when typing in inputs/textareas
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;

      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "B") {
        e.preventDefault();
        onToggleSidebar?.();
      }
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "L") {
        e.preventDefault();
        toast({
          title: "Coming soon",
          description: "Run list focus shortcut",
        });
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onToggleSidebar, toast]);

  return (
    <header className="flex items-center justify-between h-10 px-3 border-b border-border bg-background">
      <div className="flex items-center gap-2">
        {onToggleSidebar && (
          <button
            onClick={onToggleSidebar}
            className="p-1.5 hover:bg-accent rounded text-sm"
            aria-label="Toggle sidebar"
          >
            ☰
          </button>
        )}
        <button
          onClick={onToggleCommandPalette}
          className="flex-1 max-w-sm text-left px-2 py-1 text-xs text-muted-foreground hover:bg-accent rounded border border-border bg-muted/30"
        >
          Search or run a command... (Ctrl+K)
        </button>
        <span className="hidden md:inline text-xs font-semibold text-muted-foreground">PaperForge</span>
        {currentRun && (
          <div className="hidden lg:flex items-center gap-2 text-xs" aria-label="Current run status">
            <span className="max-w-48 truncate font-medium" title={currentRun.title}>{currentRun.title}</span>
            <span className="text-muted-foreground">{currentRun.status}</span>
            {currentRun.phase && <span className="text-muted-foreground">· {currentRun.phase}</span>}
          </div>
        )}
      </div>
      <div className="flex items-center gap-1">
        <span className={`hidden sm:inline-flex items-center gap-1 px-2 py-1 text-[11px] ${connectionStatus === "error" ? "text-destructive" : "text-muted-foreground"}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${connectionStatus === "connected" ? "bg-emerald-500" : connectionStatus === "connecting" ? "bg-amber-500" : "bg-destructive"}`} />
          {connectionStatus === "connected" ? "Connected" : connectionStatus === "connecting" ? "Connecting" : "Connection issue"}
        </span>
        <button
          onClick={toggleTheme}
          className="px-2 py-1 text-xs rounded hover:bg-accent"
          title="Toggle theme"
          aria-label="Toggle theme"
        >
          {mounted && theme === "dark" ? "☀" : "☾"}
        </button>
      </div>
    </header>
  );
}
