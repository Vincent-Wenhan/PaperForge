"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";

interface CommandItem {
  id: string;
  label: string;
  hint?: string;
  group: "actions" | "runs" | "papers";
  action: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [runs, setRuns] = useState<any[]>([]);
  const [library, setLibrary] = useState<any[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    Promise.all([api.listRuns(), api.listLibrary()])
      .then(([runsResp, libResp]) => {
        setRuns(runsResp || []);
        setLibrary(libResp.papers || []);
      })
      .catch(() => {});
    setQuery("");
    setSelectedIndex(0);
    setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  if (!open) return null;

  const handleNewRun = async () => {
    const run = await api.createRun("New Run");
    router.push(`/runs/${run.id}`);
    onClose();
  };

  const actions: CommandItem[] = [
    {
      id: "new-run",
      label: "New run",
      hint: "Create a new conversation",
      group: "actions",
      action: handleNewRun,
    },
  ];

  const matchedRuns: CommandItem[] = runs
    .filter((r) => !query || r.title.toLowerCase().includes(query.toLowerCase()))
    .slice(0, 5)
    .map((r) => ({
      id: `run-${r.id}`,
      label: r.title,
      hint: r.id,
      group: "runs",
      action: () => {
        router.push(`/runs/${r.id}`);
        onClose();
      },
    }));

  const matchedPapers: CommandItem[] = library
    .filter((p) => !query || p.title.toLowerCase().includes(query.toLowerCase()))
    .slice(0, 5)
    .map((p) => ({
      id: `paper-${p.paper_id}`,
      label: p.title,
      hint: "Paper",
      group: "papers",
      action: () => {
        onClose();
      },
    }));

  const filtered = [...actions, ...matchedRuns, ...matchedPapers].filter((item) =>
    !query || item.label.toLowerCase().includes(query.toLowerCase())
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      filtered[selectedIndex]?.action();
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  const groups: Record<string, CommandItem[]> = {};
  for (const item of filtered) {
    if (!groups[item.group]) groups[item.group] = [];
    groups[item.group].push(item);
  }

  let flatIndex = 0;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh] bg-black/40 animate-fade-in"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl bg-background border border-border rounded-lg shadow-xl overflow-hidden animate-slide-in"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setSelectedIndex(0);
          }}
          onKeyDown={handleKeyDown}
          placeholder="Search runs, papers, or run a command..."
          className="w-full px-4 py-3 bg-transparent border-b border-border focus:outline-none text-sm"
        />
        <div className="max-h-[400px] overflow-y-auto py-1">
          {Object.entries(groups).map(([group, items]) => (
            <div key={group}>
              <div className="px-3 py-1 text-xs font-semibold uppercase text-muted-foreground">
                {group}
              </div>
              {items.map((item) => {
                const idx = flatIndex++;
                return (
                  <button
                    key={item.id}
                    onClick={item.action}
                    onMouseEnter={() => setSelectedIndex(idx)}
                    className={`w-full flex items-center justify-between px-3 py-2 text-sm text-left ${
                      idx === selectedIndex ? "bg-accent" : "hover:bg-accent"
                    }`}
                  >
                    <span>{item.label}</span>
                    {item.hint && (
                      <span className="text-xs text-muted-foreground">{item.hint}</span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="px-3 py-4 text-sm text-muted-foreground text-center">
              No results found
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
