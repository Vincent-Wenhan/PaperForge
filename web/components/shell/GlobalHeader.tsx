"use client";

import { useEffect, useState } from "react";
import { useTheme } from "@/lib/useTheme";

interface GlobalHeaderProps {
  onToggleCommandPalette?: () => void;
}

export function GlobalHeader({ onToggleCommandPalette }: GlobalHeaderProps) {
  const { theme, toggleTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <header className="flex items-center justify-between h-10 px-3 border-b border-border bg-background">
      <button
        onClick={onToggleCommandPalette}
        className="flex-1 max-w-sm text-left px-2 py-1 text-xs text-muted-foreground hover:bg-accent rounded border border-border bg-muted/30"
      >
        Search or run a command... (Ctrl+K)
      </button>
      <div className="flex items-center gap-1">
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
