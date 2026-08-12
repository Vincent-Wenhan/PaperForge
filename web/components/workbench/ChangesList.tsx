"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { EmptyState } from "../Skeleton";
import { useToast } from "@/lib/toast";

export function ChangesList({
  appArtifactId,
  runId,
  events,
}: {
  appArtifactId?: string;
  runId?: string;
  events: any[];
}) {
  const [revisions, setRevisions] = useState<any[]>([]);

  const reload = () => {
    if (!appArtifactId) return;
    api.listAppRevisions(appArtifactId, runId)
      .then((response) => setRevisions(response.revisions || []))
      .catch(() => setRevisions([]));
  };

  useEffect(() => {
    if (!appArtifactId) {
      setRevisions([]);
      return;
    }
    reload();
  }, [appArtifactId, runId]);

  if (revisions.length > 0) {
    return (
      <div className="h-full overflow-y-auto p-3 space-y-3">
        {revisions.map((revision) => (
          <RevisionRow
            key={revision.id}
            revision={revision}
            appArtifactId={appArtifactId!}
            runId={runId}
            onRestored={reload}
          />
        ))}
      </div>
    );
  }

  const toolEvents = events.filter(
    (e) => e.type === "tool.call" || e.type === "tool.result"
  );

  if (toolEvents.length === 0) {
    return (
      <EmptyState
        icon="📝"
        title="No changes yet"
        description="As the agent modifies files, the diff history will appear here."
      />
    );
  }

  return (
    <div className="h-full overflow-y-auto p-3 space-y-2">
      <div className="text-xs text-muted-foreground mb-2">
        {toolEvents.length} agent action{toolEvents.length === 1 ? "" : "s"}
      </div>
      {toolEvents
        .slice()
        .reverse()
        .map((event, idx) => {
          const isCall = event.type === "tool.call";
          const name = event.data?.name || event.data?.tool || "tool";
          return (
            <div
              key={idx}
              className="border border-border rounded p-2 text-xs"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-mono font-medium">{name}</span>
                <span className="text-muted-foreground">
                  {isCall ? "started" : "completed"}
                </span>
              </div>
              {event.data?.args && (
                <pre className="text-xs overflow-x-auto bg-muted/30 p-2 rounded">
                  {JSON.stringify(event.data.args, null, 2)}
                </pre>
              )}
              {event.data?.result && (
                <pre className="text-xs overflow-x-auto bg-muted/30 p-2 rounded mt-1 max-h-32 overflow-y-auto">
                  {typeof event.data.result === "string"
                    ? event.data.result
                    : JSON.stringify(event.data.result, null, 2)}
                </pre>
              )}
            </div>
          );
        })}
    </div>
  );
}

function RevisionRow({
  revision,
  appArtifactId,
  runId,
  onRestored,
}: {
  revision: any;
  appArtifactId: string;
  runId?: string;
  onRestored: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [files, setFiles] = useState<any[]>([]);
  const { toast } = useToast();
  const loadDiff = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    if (files.length === 0) {
      try {
        const detail = await api.getAppRevision(appArtifactId, revision.id, runId);
        const revisionFiles = (detail.files as any[]) || [];
        setFiles(revisionFiles);
      } catch (err) {
        toast({ title: "Could not load changes", description: err instanceof Error ? err.message : String(err), variant: "error" });
        return;
      }
    }
    setExpanded(true);
  };
  const restore = async () => {
    try {
      await api.restoreAppRevision(appArtifactId, revision.id, runId);
      toast({ title: "Checkpoint restored", variant: "success" });
      onRestored();
    } catch (err) {
      toast({ title: "Restore failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
    }
  };
  return (
    <div className="border border-border rounded p-2 text-xs">
      <button onClick={loadDiff} className="w-full text-left">
        <div className="flex items-center justify-between">
          <span className="font-medium">{revision.source} revision</span>
          <span className="text-muted-foreground">{revision.changed_files?.length || 0} files</span>
        </div>
        <div className="text-muted-foreground mt-1">{revision.created_at}</div>
      </button>
      {expanded && (
        <div className="mt-2 border-t border-border pt-2 space-y-2">
          <ul className="space-y-1">
            {files.map((file) => (
              <li key={file.path} className="font-mono">
                <span className={file.before == null ? "text-green-600" : file.after == null ? "text-red-600" : "text-amber-600"}>
                  {file.before == null ? "A" : file.after == null ? "D" : "M"}
                </span>{" "}{file.path}
              </li>
            ))}
          </ul>
          <button onClick={restore} className="px-2 py-1 border border-border rounded hover:bg-accent">
            Restore checkpoint
          </button>
        </div>
      )}
    </div>
  );
}
