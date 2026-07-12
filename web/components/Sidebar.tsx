"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Paper, Run } from "@/lib/store";

interface SidebarProps {
  runs: Run[];
  library: Paper[];
  onNewRun: () => void;
  onSelectRun: (runId: string) => void;
  onRunsChanged?: () => void;
  onLibraryChanged?: () => void;
}

type RunGroupKey = "pinned" | "today" | "yesterday" | "week" | "older";

const GROUP_LABELS: Record<RunGroupKey, string> = {
  pinned: "Pinned",
  today: "Today",
  yesterday: "Yesterday",
  week: "Previous 7 days",
  older: "Older",
};

const GROUP_ORDER: RunGroupKey[] = ["pinned", "today", "yesterday", "week", "older"];

function startOfDay(d: Date): number {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x.getTime();
}

function groupRun(run: Run): RunGroupKey {
  if (run.pinned) return "pinned";
  const created = new Date(run.created_at).getTime();
  const todayStart = startOfDay(new Date());
  const dayMs = 86400000;
  if (created >= todayStart) return "today";
  if (created >= todayStart - dayMs) return "yesterday";
  if (created >= todayStart - 7 * dayMs) return "week";
  return "older";
}

export function Sidebar({
  runs,
  library,
  onNewRun,
  onSelectRun,
  onRunsChanged,
  onLibraryChanged,
}: SidebarProps) {
  const [query, setQuery] = useState("");
  const [uploading, setUploading] = useState(false);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const filtered = runs.filter((r) => {
    if (query) {
      const q = query.toLowerCase();
      if (!r.title.toLowerCase().includes(q) && !r.id.toLowerCase().includes(q)) return false;
    }
    return true;
  });

  const groups = new Map<RunGroupKey, Run[]>();
  for (const r of filtered) {
    const k = groupRun(r);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(r);
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await api.uploadPaper(file);
      onLibraryChanged?.();
    } catch (err) {
      console.error(err);
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const handleRename = async (runId: string) => {
    const title = renameValue.trim();
    if (title) {
      try {
        await api.updateRun(runId, { title });
        onRunsChanged?.();
      } catch (err) {
        console.error(err);
      }
    }
    setRenaming(null);
    setMenuFor(null);
  };

  const handleArchive = async (runId: string) => {
    try {
      await api.archiveRun(runId);
      onRunsChanged?.();
    } catch (err) {
      console.error(err);
    }
    setMenuFor(null);
  };

  const handleDelete = async (runId: string) => {
    if (!confirm("Delete this run? This cannot be undone.")) return;
    try {
      await api.deleteRun(runId);
      onRunsChanged?.();
    } catch (err) {
      console.error(err);
    }
    setMenuFor(null);
  };

  const handleTogglePin = async (run: Run) => {
    try {
      await api.updateRun(run.id, { pinned: !run.pinned });
      onRunsChanged?.();
    } catch (err) {
      console.error(err);
    }
    setMenuFor(null);
  };

  return (
    <aside className="w-64 border-r border-border flex flex-col bg-muted/30">
      <div className="p-3 border-b border-border">
        <button
          onClick={onNewRun}
          className="w-full px-3 py-2 text-sm font-medium bg-primary text-primary-foreground rounded hover:opacity-90"
        >
          + New Run
        </button>
        <div className="mt-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search runs..."
            className="w-full px-2 py-1 text-xs border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {GROUP_ORDER.map((key) => {
          const list = groups.get(key);
          if (!list || list.length === 0) return null;
          return (
            <section key={key} className="p-2">
              <h3 className="text-xs font-semibold text-muted-foreground mb-1 px-2 uppercase">
                {GROUP_LABELS[key]}
              </h3>
              <ul className="space-y-0.5">
                {list.map((run) => (
                  <RunRow
                    key={run.id}
                    run={run}
                    onSelect={onSelectRun}
                    menuOpen={menuFor === run.id}
                    onToggleMenu={() => setMenuFor(menuFor === run.id ? null : run.id)}
                    renaming={renaming === run.id}
                    renameValue={renameValue}
                    onStartRename={() => {
                      setRenameValue(run.title);
                      setRenaming(run.id);
                      setMenuFor(null);
                    }}
                    onRenameChange={setRenameValue}
                    onRenameCommit={() => handleRename(run.id)}
                    onRenameCancel={() => setRenaming(null)}
                    onArchive={() => handleArchive(run.id)}
                    onDelete={() => handleDelete(run.id)}
                    onTogglePin={() => handleTogglePin(run)}
                  />
                ))}
              </ul>
            </section>
          );
        })}
        {filtered.length === 0 && (
          <div className="p-4 text-xs text-muted-foreground">
            {query ? "No matching runs." : "No runs yet."}
          </div>
        )}
      </div>

      <div className="p-2 border-t border-border">
        <h3 className="text-xs font-semibold text-muted-foreground mb-1 px-2 uppercase">
          Library
        </h3>
        <ul className="space-y-0.5 mb-2">
          {library.map((p: Paper) => (
            <li key={p.paper_id} className="px-2 py-1.5 hover:bg-accent rounded cursor-default">
              <div className="text-sm font-medium truncate">{p.title}</div>
              <div className="text-xs text-muted-foreground">
                {p.status}
                {p.parsed_at ? " · parsed" : ""}
              </div>
            </li>
          ))}
          {library.length === 0 && (
            <li className="text-xs text-muted-foreground px-2">No papers yet</li>
          )}
        </ul>
        <label className="block">
          <input
            type="file"
            accept=".pdf"
            onChange={handleUpload}
            disabled={uploading}
            className="hidden"
          />
          <span className="block w-full text-center px-3 py-2 text-sm border border-dashed border-border rounded cursor-pointer hover:bg-accent">
            {uploading ? "Uploading..." : "+ Add Paper"}
          </span>
        </label>
      </div>
    </aside>
  );
}

interface RunRowProps {
  run: Run;
  onSelect: (id: string) => void;
  menuOpen: boolean;
  onToggleMenu: () => void;
  renaming: boolean;
  renameValue: string;
  onStartRename: () => void;
  onRenameChange: (v: string) => void;
  onRenameCommit: () => void;
  onRenameCancel: () => void;
  onArchive: () => void;
  onDelete: () => void;
  onTogglePin: () => void;
}

function RunRow({
  run,
  onSelect,
  menuOpen,
  onToggleMenu,
  renaming,
  renameValue,
  onStartRename,
  onRenameChange,
  onRenameCommit,
  onRenameCancel,
  onArchive,
  onDelete,
  onTogglePin,
}: RunRowProps) {
  if (renaming) {
    return (
      <li className="px-2 py-1">
        <input
          autoFocus
          type="text"
          value={renameValue}
          onChange={(e) => onRenameChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onRenameCommit();
            if (e.key === "Escape") onRenameCancel();
          }}
          onBlur={onRenameCommit}
          className="w-full px-1 py-0.5 text-sm border border-primary rounded focus:outline-none"
        />
      </li>
    );
  }

  return (
    <li className="group relative">
      <button
        onClick={() => onSelect(run.id)}
        className="w-full text-left px-2 py-1.5 text-sm rounded hover:bg-accent"
      >
        <div className="font-medium truncate flex items-center gap-1">
          {run.pinned && <span className="text-xs">📌</span>}
          {run.title}
        </div>
        <div className="text-xs text-muted-foreground">
          {run.status} · {run.phase || "init"}
        </div>
      </button>
      <button
        onClick={onToggleMenu}
        className="absolute right-1 top-1.5 opacity-0 group-hover:opacity-100 hover:bg-accent rounded px-1 text-xs"
      >
        ···
      </button>
      {menuOpen && (
        <div className="absolute right-1 top-7 z-10 bg-background border border-border rounded shadow-md py-1 text-xs w-36">
          <button
            onClick={onStartRename}
            className="block w-full text-left px-3 py-1.5 hover:bg-accent"
          >
            Rename
          </button>
          <button
            onClick={onTogglePin}
            className="block w-full text-left px-3 py-1.5 hover:bg-accent"
          >
            {run.pinned ? "Unpin" : "Pin"}
          </button>
          <button
            onClick={onArchive}
            className="block w-full text-left px-3 py-1.5 hover:bg-accent"
          >
            Archive
          </button>
          <button
            onClick={onDelete}
            className="block w-full text-left px-3 py-1.5 hover:bg-accent text-destructive"
          >
            Delete
          </button>
        </div>
      )}
    </li>
  );
}
