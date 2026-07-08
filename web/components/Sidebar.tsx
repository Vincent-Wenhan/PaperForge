"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Paper } from "@/lib/store";

interface SidebarProps {
  runs: any[];
  library: any[];
  onNewRun: () => void;
  onSelectRun: (runId: string) => void;
}

export function Sidebar({ runs, library, onNewRun, onSelectRun }: SidebarProps) {
  const [uploading, setUploading] = useState(false);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await api.uploadPaper(file);
      window.location.reload();
    } catch (err) {
      console.error(err);
    } finally {
      setUploading(false);
    }
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
      </div>

      <div className="flex-1 overflow-y-auto">
        <section className="p-3">
          <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase">
            Recent Runs
          </h3>
          <ul className="space-y-1">
            {runs.map((run) => (
              <li key={run.id}>
                <button
                  onClick={() => onSelectRun(run.id)}
                  className="w-full text-left px-2 py-1.5 text-sm rounded hover:bg-accent truncate"
                >
                  {run.title}
                </button>
              </li>
            ))}
            {runs.length === 0 && (
              <li className="text-xs text-muted-foreground px-2">No runs yet</li>
            )}
          </ul>
        </section>

        <section className="p-3 border-t border-border">
          <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase">
            Library
          </h3>
          <ul className="space-y-1">
            {library.map((p: Paper) => (
              <li key={p.paper_id}>
                <div className="px-2 py-1.5 text-sm truncate">{p.title}</div>
              </li>
            ))}
            {library.length === 0 && (
              <li className="text-xs text-muted-foreground px-2">No papers yet</li>
            )}
          </ul>
        </section>
      </div>

      <div className="p-3 border-t border-border">
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
