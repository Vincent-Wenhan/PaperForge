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
}

const SANDBOX_STATUS_LABEL: Record<string, string> = {
  running: "Running",
  pending: "Starting",
  stopped: "Stopped",
  error: "Error",
};

export function PreviewPanel() {
  const sandbox = useAppStore((s) => s.sandbox);
  const artifacts = useAppStore((s) => s.artifacts);
  const events = useAppStore((s) => s.events);

  const [activeTab, setActiveTab] = useState<Tab>("preview");
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [tabs, setTabs] = useState<EditorTab[]>([]);
  const [activeTabPath, setActiveTabPath] = useState<string | null>(null);

  useEffect(() => {
    if (!sandbox) {
      setTree([]);
      return;
    }
    let active = true;
    api.getFileTree(sandbox.id)
      .then((resp) => {
        if (!active) return;
        setTree(buildNestedTree(resp.tree || []));
      })
      .catch(() => {
        if (active) setTree([]);
      });
    return () => {
      active = false;
    };
  }, [sandbox]);

  const refreshTree = async () => {
    if (!sandbox?.id) return;
    try {
      const resp = await api.getFileTree(sandbox.id);
      setTree(buildNestedTree(resp.tree || []));
    } catch (err) {
      console.error("Failed to refresh tree:", err);
    }
  };

  const openFile = async (path: string) => {
    if (!sandbox) return;
    const existing = tabs.find((t) => t.path === path);
    if (existing) {
      setActiveTabPath(path);
      return;
    }
    try {
      const resp = await api.readFile(sandbox.id, path);
      const newTab: EditorTab = { path, content: resp.content, dirty: false };
      setTabs((prev) => [...prev, newTab]);
      setActiveTabPath(path);
    } catch (err) {
      console.error("Failed to open file:", err);
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
      prev.map((t) => (t.path === path ? { ...t, content, dirty: true } : t)),
    );
  };

  const saveFile = async (path: string) => {
    if (!sandbox) return;
    const tab = tabs.find((t) => t.path === path);
    if (!tab) return;
    try {
      await api.writeFile(sandbox.id, path, tab.content);
      setTabs((prev) => prev.map((t) => (t.path === path ? { ...t, dirty: false } : t)));
    } catch (err) {
      console.error("Failed to save file:", err);
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
            : "No sandbox"}
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        {activeTab === "preview" && <PreviewFrame sandbox={sandbox} />}
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
          <ChangesList artifacts={artifacts} events={events} />
        )}
        {activeTab === "tests" && (
          <TestsTab artifacts={artifacts} sandbox={sandbox} />
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
}

function PreviewFrame({ sandbox }: PreviewFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [viewport, setViewport] = useState<"desktop" | "tablet" | "mobile">("desktop");

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
      await api.restartSandbox(sandbox.id);
    } catch (err) {
      console.error("Failed to restart sandbox:", err);
    }
  };

  const handleStop = async () => {
    if (!sandbox?.id) return;
    try {
      await api.stopSandbox(sandbox.id);
    } catch (err) {
      console.error("Failed to stop sandbox:", err);
    }
  };

  const viewportWidth = {
    desktop: "100%",
    tablet: "768px",
    mobile: "375px",
  }[viewport];

  if (!sandbox?.id) {
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
            theme="vs-light"
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
  artifacts: any[];
  events: any[];
}

function ChangesList({ artifacts, events }: ChangesListProps) {
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

// ===== Tests Tab =====

interface TestsTabProps {
  artifacts: any[];
  sandbox?: any;
}

function TestsTab({ artifacts, sandbox }: TestsTabProps) {
  const verification = artifacts.find((a) => a.type === "verification_report");
  const report = verification?.data?.report ?? verification?.data ?? null;

  const checks = [
    {
      id: "build",
      label: "Build",
      status: report?.build_succeeded ? "pass" : "fail",
      detail: report?.build_succeeded
        ? "Build succeeded"
        : "Build failed",
    },
    {
      id: "typecheck",
      label: "Type check",
      status: report?.type_errors?.length === 0 ? "pass" : "fail",
      detail: report?.type_errors?.length
        ? `${report.type_errors.length} type error(s)`
        : "No type errors",
    },
    {
      id: "lint",
      label: "Lint",
      status: report?.lint_errors?.length === 0 ? "pass" : "fail",
      detail: report?.lint_errors?.length
        ? `${report.lint_errors.length} lint error(s)`
        : "No lint errors",
    },
    {
      id: "preview",
      label: "Preview",
      status: sandbox?.status === "running" ? "pass" : "fail",
      detail: sandbox?.status === "running"
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
            {check.status === "pass" ? "PASS" : "FAIL"}
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
