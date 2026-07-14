"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Panel,
  PanelGroup,
  PanelResizeHandle,
} from "react-resizable-panels";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { ConsoleLogs } from "./ConsoleLogs";
import { VerificationReportView } from "./VerificationReportView";
import { ArtifactCard } from "./ArtifactCard";
import { EmptyState } from "./Skeleton";
import { useTheme } from "@/lib/useTheme";
import { useToast } from "@/lib/toast";

const MonacoEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.default), {
  ssr: false,
  loading: () => <div className="p-4 text-muted-foreground">Loading editor...</div>,
});

type Tab = "preview" | "code" | "changes" | "tests" | "artifacts" | "logs";

const WORKBENCH_TABS: { id: Tab; label: string }[] = [
  { id: "preview", label: "Preview" },
  { id: "code", label: "Code" },
  { id: "changes", label: "Changes" },
  { id: "tests", label: "Tests" },
  { id: "artifacts", label: "Artifacts" },
  { id: "logs", label: "Logs" },
];

interface TreeNode {
  path: string;
  type: "file" | "directory";
  size?: number;
  children?: TreeNode[];
}

interface EditorTab {
  path: string;
  content: string;
  dirty: boolean;
  saveState?: "saved" | "saving" | "error";
}

const SANDBOX_STATUS_LABEL: Record<string, string> = {
  running: "Running",
  pending: "Starting",
  stopped: "Stopped",
  error: "Error",
};

export function PreviewPanel() {
  const currentRun = useAppStore((s) => s.currentRun);
  const sandbox = useAppStore((s) => s.sandbox);
  const preview = useAppStore((s) => s.preview);
  const artifacts = useAppStore((s) => s.artifacts);
  const events = useAppStore((s) => s.events);
  const appArtifactId = artifacts.find((artifact) => artifact.type === "nextjs_app")?.id;
  const { toast } = useToast();

  const [activeTab, setActiveTab] = useState<Tab>("preview");
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [tabs, setTabs] = useState<EditorTab[]>([]);
  const [activeTabPath, setActiveTabPath] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (appArtifactId) {
      api.listAppTree(appArtifactId, currentRun?.id)
        .then((resp) => {
          if (active) setTree(buildNestedTree(resp.tree || []));
        })
        .catch(() => {
          if (active) {
            setTree([]);
            toast({ title: "Workspace unavailable", description: "Could not load the app file tree.", variant: "error" });
          }
        });
      return () => {
        active = false;
      };
    }
    if (!sandbox) {
      setTree([]);
      return;
    }
    api.getFileTree(sandbox.id)
      .then((resp) => {
        if (!active) return;
        setTree(buildNestedTree(resp.tree || []));
      })
      .catch(() => {
        if (active) {
          setTree([]);
          toast({ title: "Workspace unavailable", description: "Could not load the sandbox file tree.", variant: "error" });
        }
      });
    return () => {
      active = false;
    };
  }, [appArtifactId, currentRun?.id, sandbox?.id]);

  const refreshTree = async () => {
    if (appArtifactId) {
      try {
        const resp = await api.listAppTree(appArtifactId, currentRun?.id);
        setTree(buildNestedTree(resp.tree || []));
      } catch (err) {
      toast({ title: "Refresh failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
      }
      return;
    }
    if (!sandbox?.id) return;
    try {
      const resp = await api.getFileTree(sandbox.id);
      setTree(buildNestedTree(resp.tree || []));
    } catch (err) {
      toast({ title: "Refresh failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
    }
  };

  const openFile = async (path: string) => {
    if (!sandbox && !appArtifactId) return;
    const existing = tabs.find((t) => t.path === path);
    if (existing) {
      setActiveTabPath(path);
      return;
    }
    try {
      const resp = appArtifactId
        ? await api.readAppFile(appArtifactId, path, currentRun?.id)
        : await api.readFile(sandbox!.id, path);
      const newTab: EditorTab = { path, content: resp.content, dirty: false, saveState: "saved" };
      setTabs((prev) => [...prev, newTab]);
      setActiveTabPath(path);
    } catch (err) {
      toast({ title: "Open file failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
    }
  };

  const closeTab = (path: string) => {
    setTabs((prev) => {
      const idx = prev.findIndex((t) => t.path === path);
      const filtered = prev.filter((t) => t.path !== path);
      if (activeTabPath === path) {
        const newIdx = Math.min(idx, filtered.length - 1);
        setActiveTabPath(filtered[newIdx]?.path ?? null);
      }
      return filtered;
    });
  };

  const updateTabContent = (path: string, content: string) => {
    setTabs((prev) =>
      prev.map((t) => (t.path === path ? { ...t, content, dirty: true, saveState: "saved" } : t)),
    );
  };

  const saveFile = async (path: string) => {
    if (!sandbox && !appArtifactId) return;
    const tab = tabs.find((t) => t.path === path);
    if (!tab) return;
    setTabs((prev) => prev.map((t) => (t.path === path ? { ...t, saveState: "saving" } : t)));
    try {
      if (appArtifactId) {
        await api.writeAppFile(appArtifactId, path, tab.content, currentRun?.id);
      } else {
        await api.writeFile(sandbox!.id, path, tab.content);
      }
      setTabs((prev) => prev.map((t) => (t.path === path ? { ...t, dirty: false, saveState: "saved" } : t)));
    } catch (err) {
      setTabs((prev) => prev.map((t) => (t.path === path ? { ...t, saveState: "error" } : t)));
      toast({ title: "Save failed", description: err instanceof Error ? err.message : String(err), variant: "error" });
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between border-b border-border bg-muted/30">
        <div className="flex" role="tablist">
          {WORKBENCH_TABS.map((tab) => {
            const count =
              tab.id === "artifacts"
                ? artifacts.length
                : tab.id === "logs"
                  ? events.length
                  : undefined;
            return (
              <button
                key={tab.id}
                role="tab"
                aria-selected={activeTab === tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-3 py-2 text-xs border-b-2 transition-colors ${
                  activeTab === tab.id
                    ? "border-primary font-medium bg-background"
                    : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/50"
                }`}
              >
                {tab.label}
                {count !== undefined && count > 0 && (
                  <span className="ml-1 text-muted-foreground">{count}</span>
                )}
              </button>
            );
          })}
        </div>
        <div className="pr-2 text-xs text-muted-foreground">
          {sandbox
            ? `Sandbox: ${SANDBOX_STATUS_LABEL[sandbox.status] || sandbox.status}`
            : appArtifactId
              ? "App workspace ready"
              : "No sandbox"}
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        {activeTab === "preview" && <PreviewFrame sandbox={sandbox} preview={preview} />}
        {activeTab === "code" && (
          <CodeEditor
            tree={tree}
            tabs={tabs}
            activeTabPath={activeTabPath}
            sandbox={sandbox}
            onOpenFile={openFile}
            onCloseTab={closeTab}
            onSaveFile={saveFile}
            onContentChange={updateTabContent}
            onRefreshTree={refreshTree}
          />
        )}
        {activeTab === "changes" && (
          <ChangesList appArtifactId={appArtifactId} runId={currentRun?.id} events={events} />
        )}
        {activeTab === "tests" && (
          <TestsTab artifacts={artifacts} sandbox={sandbox} preview={preview} />
        )}
        {activeTab === "artifacts" && <ArtifactsList artifacts={artifacts} />}
        {activeTab === "logs" && <ConsoleLogs sandboxId={sandbox?.id} />}
      </div>
    </div>
  );
}

// ===== Preview Frame =====

interface PreviewFrameProps {
  sandbox?: any;
  preview?: any;
}

function PreviewFrame({ sandbox, preview }: PreviewFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [viewport, setViewport] = useState<"desktop" | "tablet" | "mobile">("desktop");
  const { toast } = useToast();

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
          src={api.getPreviewUrl(sandbox.id)}
          className="border-0 transition-all"
          style={{ width: viewportWidth, height: "100%" }}
          title="Preview"
        />
      </div>
    </div>
  );
}

// ===== Code Editor with Tabs =====

interface CodeEditorProps {
  tree: TreeNode[];
  tabs: EditorTab[];
  activeTabPath: string | null;
  sandbox?: any;
  onOpenFile: (path: string) => void;
  onCloseTab: (path: string) => void;
  onSaveFile: (path: string) => void;
  onContentChange: (path: string, content: string) => void;
  onRefreshTree: () => Promise<void>;
}

function CodeEditor({
  tree,
  tabs,
  activeTabPath,
  sandbox,
  onOpenFile,
  onCloseTab,
  onSaveFile,
  onContentChange,
  onRefreshTree,
}: CodeEditorProps) {
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const { theme } = useTheme();

  const toggleDir = (path: string) => {
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const activeTab = tabs.find((t) => t.path === activeTabPath);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        if (activeTabPath) onSaveFile(activeTabPath);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activeTabPath, onSaveFile]);

  return (
    <div className="flex h-full">
      <div className="w-56 border-r border-border overflow-y-auto bg-muted/30 flex flex-col">
        <div className="flex items-center justify-between px-2 py-1 border-b border-border">
          <span className="text-xs font-semibold">FILES</span>
          <div className="flex gap-1">
            <button
              onClick={onRefreshTree}
              className="text-xs hover:bg-muted rounded px-1"
              title="Refresh tree"
            >
              ↻
            </button>
          </div>
        </div>
        <FileTreeView
          tree={tree}
          expandedDirs={expandedDirs}
          onToggleDir={toggleDir}
          onSelectFile={onOpenFile}
        />
      </div>

      <div className="flex-1 flex flex-col">
        {tabs.length > 0 && (
          <div className="flex items-center border-b border-border bg-muted/30 overflow-x-auto" role="tablist">
            {tabs.map((tab) => (
              <div
                key={tab.path}
                className={`flex items-center gap-1 px-3 py-1.5 text-xs border-r border-border cursor-pointer ${
                  activeTabPath === tab.path ? "bg-background font-medium" : "hover:bg-muted/50"
                }`}
                onClick={() => onOpenFile(tab.path)}
                role="tab"
                aria-selected={activeTabPath === tab.path}
              >
                <span>{tab.path.split("/").pop()}</span>
                {tab.dirty && <span className="text-amber-500">●</span>}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onCloseTab(tab.path);
                  }}
                  className="ml-1 hover:text-destructive"
                  aria-label="Close tab"
                >
                  ×
                </button>
              </div>
            ))}
            {activeTab && (
              <span className="ml-auto shrink-0 px-3 text-xs text-muted-foreground" role="status">
                {activeTab.saveState === "saving"
                  ? "Saving..."
                  : activeTab.saveState === "error"
                    ? "Save failed"
                    : activeTab.dirty
                      ? "Unsaved changes"
                      : "Saved"}
              </span>
            )}
          </div>
        )}

        {activeTab ? (
          <MonacoEditor
            height="100%"
            language={getLanguage(activeTab.path)}
            value={activeTab.content}
            onChange={(value) => onContentChange(activeTab.path, value || "")}
            onMount={(editor) => {
              editor.addCommand(2048 | 49, () => onSaveFile(activeTab.path));
            }}
            theme={theme === "dark" ? "vs-dark" : "vs-light"}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              wordWrap: "on",
              scrollBeyondLastLine: false,
              automaticLayout: true,
              tabSize: 2,
            }}
          />
        ) : (
          <EmptyState
            icon="📄"
            title="Select a file from the tree"
            description="Click any file in the file tree to open it in the editor."
          />
        )}
      </div>
    </div>
  );
}

// ===== File Tree View =====

interface FileTreeViewProps {
  tree: TreeNode[];
  expandedDirs: Set<string>;
  onToggleDir: (path: string) => void;
  onSelectFile: (path: string) => void;
}

function FileTreeView({
  tree,
  expandedDirs,
  onToggleDir,
  onSelectFile,
}: FileTreeViewProps) {
  const renderNode = (node: TreeNode, depth: number = 0) => {
    const name = node.path.split("/").pop();
    const isExpanded = expandedDirs.has(node.path);

    if (node.type === "directory") {
      return (
        <div key={node.path}>
          <button
            onClick={() => onToggleDir(node.path)}
            className="w-full text-left py-1 text-xs hover:bg-accent flex items-center gap-1"
            style={{ paddingLeft: `${depth * 12 + 8}px` }}
          >
            <span className="text-muted-foreground">{isExpanded ? "▼" : "▶"}</span>
            <span>{name}/</span>
          </button>
          {isExpanded && node.children && (
            <div>
              {node.children
                .sort((a, b) => {
                  if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
                  return a.path.localeCompare(b.path);
                })
                .map((child) => renderNode(child, depth + 1))}
            </div>
          )}
        </div>
      );
    }

    return (
      <button
        key={node.path}
        onClick={() => onSelectFile(node.path)}
        className="w-full text-left py-1 text-xs hover:bg-accent"
        style={{ paddingLeft: `${depth * 12 + 20}px` }}
      >
        {name}
      </button>
    );
  };

  return (
    <div>
      {tree
        .sort((a, b) => {
          if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
          return a.path.localeCompare(b.path);
        })
        .map((node) => renderNode(node))}
    </div>
  );
}

// ===== Artifacts List =====

function ArtifactsList({ artifacts }: { artifacts: any[] }) {
  if (!artifacts || artifacts.length === 0) {
    return (
      <EmptyState
        icon="📦"
        title="No artifacts yet"
        description="Run the pipeline to generate artifacts. Capability cards, PRDs, and verification reports will appear here."
      />
    );
  }
  return (
    <div className="h-full overflow-y-auto p-3 space-y-2">
      {artifacts.map((artifact) => (
        <ArtifactCard
          key={artifact.id}
          type={artifact.type}
          path={artifact.path || ""}
          artifactId={artifact.id}
          data={artifact.data}
        />
      ))}
    </div>
  );
}

// ===== Changes Tab =====

interface ChangesListProps {
  appArtifactId?: string;
  runId?: string;
  events: any[];
}

function ChangesList({ appArtifactId, runId, events }: ChangesListProps) {
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
        setFiles(detail.files || []);
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

// ===== Tests Tab =====

interface TestsTabProps {
  artifacts: any[];
  sandbox?: any;
  preview?: any;
}

function TestsTab({ artifacts, sandbox, preview }: TestsTabProps) {
  const verification = artifacts.find((a) => a.type === "verification_report");
  const report = verification?.data?.report ?? verification?.data ?? null;

  type CheckStatus = "pass" | "fail" | "pending";
  type VerificationCheck = {
    id: string;
    label: string;
    status: CheckStatus;
    detail: string;
  };

  const layerChecks = Array.isArray(report?.layers)
    ? report.layers.map((layer: any) => ({
        id: layer.id,
        label: layer.name || layer.id,
        status: (layer.status === "passed" ? "pass" : layer.status === "failed" ? "fail" : "pending") as CheckStatus,
        detail: layer.fallback_reason || layer.reason || layer.status,
      }))
    : [];
  const checks: VerificationCheck[] = layerChecks.length > 0 ? layerChecks : [
    {
      id: "build",
      label: "Build",
      status: report ? (report.build_succeeded ? "pass" : "fail") : "pending",
      detail: report?.build_succeeded
        ? "Build succeeded"
        : "Build failed",
    },
    {
      id: "typecheck",
      label: "Type check",
      status: report ? (report.type_errors?.length === 0 ? "pass" : "fail") : "pending",
      detail: report?.type_errors?.length
        ? `${report.type_errors.length} type error(s)`
        : "No type errors",
    },
    {
      id: "lint",
      label: "Lint",
      status: report ? (report.lint_errors?.length === 0 ? "pass" : "fail") : "pending",
      detail: report?.lint_errors?.length
        ? `${report.lint_errors.length} lint error(s)`
        : "No lint errors",
    },
    {
      id: "preview",
      label: "Preview",
      status: preview?.status === "running" ? "pass" : preview?.status === "degraded" ? "fail" : "pending",
      detail: preview?.status === "degraded"
        ? preview.error || "Preview environment degraded"
        : preview?.status === "running"
        ? "Preview server running"
        : "Preview not started",
    },
  ];

  return (
    <div className="h-full overflow-y-auto p-3 space-y-2">
      <div className="text-xs text-muted-foreground mb-2">Verification checks</div>
      {checks.map((check) => (
        <div
          key={check.id}
          className="flex items-center justify-between border border-border rounded p-2 text-xs"
        >
          <div>
            <div className="font-medium">{check.label}</div>
            <div className="text-muted-foreground">{check.detail}</div>
          </div>
          <span
            className={`px-2 py-0.5 rounded font-medium ${
              check.status === "pass"
                ? "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200"
                : "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200"
            }`}
          >
            {check.status === "pass" ? "PASS" : check.status === "fail" ? "FAIL" : "PENDING"}
          </span>
        </div>
      ))}
      {report && (
        <div className="mt-4">
          <VerificationReportView report={report} />
        </div>
      )}
    </div>
  );
}

// ===== Utility functions =====

function getLanguage(path: string): string {
  if (path.endsWith(".tsx")) return "typescript";
  if (path.endsWith(".ts")) return "typescript";
  if (path.endsWith(".jsx")) return "javascript";
  if (path.endsWith(".js")) return "javascript";
  if (path.endsWith(".json")) return "json";
  if (path.endsWith(".css")) return "css";
  if (path.endsWith(".md")) return "markdown";
  return "plaintext";
}

function buildNestedTree(flatTree: any[]): TreeNode[] {
  const root: TreeNode[] = [];
  const dirMap = new Map<string, TreeNode>();

  const sorted = [...flatTree].sort((a, b) => a.path.localeCompare(b.path));

  for (const item of sorted) {
    const parts = item.path.split("/");
    const name = parts[parts.length - 1];

    if (item.type === "directory") {
      const node: TreeNode = {
        path: item.path,
        type: "directory",
        children: [],
      };
      dirMap.set(item.path, node);

      const parentPath = parts.slice(0, -1).join("/");
      if (parentPath && dirMap.has(parentPath)) {
        dirMap.get(parentPath)!.children!.push(node);
      } else {
        root.push(node);
      }
    } else {
      const node: TreeNode = {
        path: item.path,
        type: "file",
        size: item.size || 0,
      };

      const parentPath = parts.slice(0, -1).join("/");
      if (parentPath && dirMap.has(parentPath)) {
        dirMap.get(parentPath)!.children!.push(node);
      } else {
        root.push(node);
      }
    }
  }

  return root;
}

function countFiles(tree: TreeNode[]): number {
  let count = 0;
  for (const node of tree) {
    if (node.type === "file") {
      count++;
    } else if (node.children) {
      count += countFiles(node.children);
    }
  }
  return count;
}
