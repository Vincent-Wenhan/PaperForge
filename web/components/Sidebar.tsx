"use client";

import { useState } from "react";
import { api, triggerBrowserDownload } from "@/lib/api";
import { useIsMobile } from "@/lib/useMediaQuery";
import type { Paper, Run } from "@/lib/store";
import { useToast } from "@/lib/toast";

interface SidebarProps {
  runs: Run[];
  library: Paper[];
  onNewRun: () => void;
  onSelectRun: (runId: string) => void;
  currentRunId?: string | null;
  onRunsChanged?: () => void;
  onLibraryChanged?: () => void;
  onOpenPaper?: (paperId: string) => void;
  onAttachPaper?: (paper: Paper) => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  onCloseMobile?: () => void;
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
  currentRunId,
  onRunsChanged,
  onLibraryChanged,
  onOpenPaper,
  onAttachPaper,
  collapsed = false,
  onToggleCollapse,
  onCloseMobile,
}: SidebarProps) {
  const isMobile = useIsMobile();
  const [query, setQuery] = useState("");
  const [uploading, setUploading] = useState(false);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [paperMenuFor, setPaperMenuFor] = useState<string | null>(null);
  const [paperRenaming, setPaperRenaming] = useState<string | null>(null);
  const [paperRenameValue, setPaperRenameValue] = useState("");
  const { toast } = useToast();

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
      toast({ title: "Upload failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
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
        toast({ title: "Rename failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
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
      toast({ title: "Archive failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
    }
    setMenuFor(null);
  };

  const handleDelete = async (runId: string) => {
    if (!confirm("Delete this run? This cannot be undone.")) return;
    try {
      await api.deleteRun(runId);
      onRunsChanged?.();
    } catch (err) {
      toast({ title: "Delete failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
    }
    setMenuFor(null);
  };

  const handleTogglePin = async (run: Run) => {
    try {
      await api.updateRun(run.id, { pinned: !run.pinned });
      onRunsChanged?.();
    } catch (err) {
      toast({ title: "Pin update failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
    }
    setMenuFor(null);
  };

  const handlePaperRename = async (paperId: string) => {
    const title = paperRenameValue.trim();
    if (title) {
      try {
        await api.renamePaper(paperId, title);
        onLibraryChanged?.();
      } catch (err) {
        toast({ title: "Paper rename failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
      }
    }
    setPaperMenuFor(null);
    setPaperRenaming(null);
  };

  const handlePaperDelete = async (paperId: string) => {
    if (!confirm("Delete this paper? This cannot be undone.")) return;
    try {
      await api.deletePaper(paperId);
      onLibraryChanged?.();
    } catch (err) {
      toast({ title: "Paper delete failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
    }
    setPaperMenuFor(null);
  };

  const handlePaperDownload = async (paperId: string) => {
    try {
      const blob = await api.downloadPaperPdf(paperId);
      triggerBrowserDownload(blob, `${paperId}.pdf`);
    } catch (err) {
      toast({ title: "Paper download failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
    }
    setPaperMenuFor(null);
  };

  const handleAttachPaper = (paper: Paper) => {
    onAttachPaper?.(paper);
    setPaperMenuFor(null);
  };

  const handleOpenPaper = (paperId: string) => {
    onOpenPaper?.(paperId);
    setPaperMenuFor(null);
  };

  // Collapsed desktop sidebar
  if (!isMobile && collapsed) {
    return (
      <aside
        className="w-14 border-r border-border bg-muted/30 flex flex-col items-center py-3 gap-3"
        aria-label="Navigation (collapsed)"
      >
        <button
          onClick={onToggleCollapse}
          className="p-2 hover:bg-accent rounded"
          aria-label="Expand sidebar"
        >
          ▶
        </button>
        <button
          onClick={onNewRun}
          className="p-2 hover:bg-accent rounded"
          aria-label="New run"
        >
          +
        </button>
      </aside>
    );
  }

  const sidebarContent = (
    <>
      <div className="p-3 border-b border-border">
        <button
          onClick={onNewRun}
          className="w-full px-3 py-2 text-sm font-medium bg-primary text-primary-foreground rounded hover:opacity-90"
          aria-label="Create new run"
        >
          + New Run
        </button>
        <div className="mt-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search runs..."
            aria-label="Search runs"
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
                    currentRunId={currentRunId}
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
            <PaperRow
              key={p.paper_id}
              paper={p}
              onOpen={() => handleOpenPaper(p.paper_id)}
              onAttach={() => handleAttachPaper(p)}
              menuOpen={paperMenuFor === p.paper_id}
              onToggleMenu={() =>
                setPaperMenuFor(paperMenuFor === p.paper_id ? null : p.paper_id)
              }
              renaming={paperRenaming === p.paper_id}
              renameValue={paperRenameValue}
              onStartRename={() => {
                setPaperRenameValue(p.title);
                setPaperRenaming(p.paper_id);
                setPaperMenuFor(null);
              }}
              onRenameChange={setPaperRenameValue}
              onRenameCommit={() => handlePaperRename(p.paper_id)}
              onRenameCancel={() => setPaperRenaming(null)}
              onDownload={() => handlePaperDownload(p.paper_id)}
              onDelete={() => handlePaperDelete(p.paper_id)}
            />
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
    </>
  );

  if (isMobile) {
    return (
      <>
        <aside
          className="mobile-sidebar open w-64 border-r border-border bg-muted/30 flex flex-col"
          aria-label="Navigation"
        >
          {sidebarContent}
        </aside>
        <div
          className="mobile-backdrop"
          onClick={onCloseMobile}
          aria-hidden="true"
        />
      </>
    );
  }

  return (
    <aside
      className="w-64 border-r border-border bg-muted/30 flex flex-col"
      aria-label="Run navigation"
    >
      {sidebarContent}
    </aside>
  );
}

interface RunRowProps {
  run: Run;
  currentRunId?: string | null;
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

export function RunRow({
  run,
  currentRunId,
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
        aria-current={currentRunId === run.id ? "page" : undefined}
        className={`w-full text-left px-2 py-1.5 text-sm rounded hover:bg-accent ${
          currentRunId === run.id ? "bg-accent" : ""
        }`}
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

interface PaperRowProps {
  paper: Paper;
  onOpen: () => void;
  onAttach: () => void;
  menuOpen: boolean;
  onToggleMenu: () => void;
  renaming: boolean;
  renameValue: string;
  onStartRename: () => void;
  onRenameChange: (v: string) => void;
  onRenameCommit: () => void;
  onRenameCancel: () => void;
  onDownload: () => void;
  onDelete: () => void;
}

function PaperRow({
  paper,
  onOpen,
  onAttach,
  menuOpen,
  onToggleMenu,
  renaming,
  renameValue,
  onStartRename,
  onRenameChange,
  onRenameCommit,
  onRenameCancel,
  onDownload,
  onDelete,
}: PaperRowProps) {
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
        onClick={onOpen}
        className="w-full text-left px-2 py-1.5 text-sm rounded hover:bg-accent"
      >
        <div className="font-medium truncate">{paper.title}</div>
        <div className="text-xs text-muted-foreground">
          {paper.status}
          {paper.parsed_at ? " · parsed" : ""}
        </div>
      </button>
      <button
        onClick={onToggleMenu}
        className="absolute right-1 top-1.5 opacity-0 group-hover:opacity-100 hover:bg-accent rounded px-1 text-xs"
      >
        ···
      </button>
      {menuOpen && (
        <div className="absolute right-1 top-7 z-10 bg-background border border-border rounded shadow-md py-1 text-xs w-40">
          <button
            onClick={onAttach}
            className="block w-full text-left px-3 py-1.5 hover:bg-accent"
          >
            Add to current chat
          </button>
          <button
            onClick={onOpen}
            className="block w-full text-left px-3 py-1.5 hover:bg-accent"
          >
            Open
          </button>
          <button
            onClick={onStartRename}
            className="block w-full text-left px-3 py-1.5 hover:bg-accent"
          >
            Rename
          </button>
          <button
            onClick={onDownload}
            className="block w-full text-left px-3 py-1.5 hover:bg-accent"
          >
            Download PDF
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
