"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { ConsoleLogs } from "./ConsoleLogs";
import { VerificationReportView } from "./VerificationReportView";
import { ArtifactCard } from "./ArtifactCard";

const MonacoEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.default), {
  ssr: false,
  loading: () => <div className="p-4 text-muted-foreground">Loading editor...</div>,
});

type Tab = "preview" | "files" | "artifacts" | "console" | "verification";

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

export function PreviewPanel() {
  const sandbox = useAppStore((s) => s.sandbox);
  const artifacts = useAppStore((s) => s.artifacts);
  const currentRun = useAppStore((s) => s.currentRun);
  const activeTab = useAppStore((s) => s.activeTab);
  const setActiveTab = useAppStore((s) => s.setActiveTab);

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
    return () => { active = false; };
  }, [sandbox]);

  const progress = useMemo(() => {
    const capability = artifacts.find((a) => a.type === "capability_card");
    const prd = artifacts.find((a) => a.type === "prd");
    const app = artifacts.find((a) => a.type === "nextjs_app");
    const verification = artifacts.find((a) => a.type === "verification_report");
    const report = verification?.data?.report ?? verification?.data ?? null;
    const previewReady = Boolean(sandbox?.id) && sandbox?.status === "running";

    return [
      { id: "capability", label: "Capability card", status: capability ? "complete" : "pending" },
      { id: "prd", label: "PRD", status: prd ? "complete" : "pending" },
      { id: "app", label: "App generated", status: app ? "complete" : "pending" },
      {
        id: "verified",
        label: "Build verified",
        status: report?.build_succeeded ? "complete" : verification ? "error" : "pending",
      },
      { id: "preview", label: "Live preview", status: previewReady ? "complete" : "pending" },
    ];
  }, [artifacts, sandbox]);

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

  const tabs_list: Tab[] = ["preview", "files", "artifacts", "console", "verification"];

  return (
    <div className="flex-1 flex flex-col h-full">
      <div className="flex border-b border-border bg-muted/30" role="tablist">
        {tabs_list.map((t) => (
          <button
            key={t}
            onClick={() => setActiveTab(t)}
            role="tab"
            aria-selected={activeTab === t}
            className={`px-4 py-2 text-sm border-b-2 capitalize transition-colors ${
              activeTab === t
                ? "border-primary font-medium bg-background"
                : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/50"
            }`}
          >
            {t}
            {t === "files" && tree.length > 0 && (
              <span className="ml-1 text-xs text-muted-foreground">
                ({countFiles(tree)})
              </span>
            )}
            {t === "artifacts" && artifacts.length > 0 && (
              <span className="ml-1 text-xs text-muted-foreground">
                ({artifacts.length})
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-hidden">
        {activeTab === "preview" && (
          <PreviewFrame sandbox={sandbox} progress={progress} phase={currentRun?.phase} />
        )}
        {activeTab === "files" && (
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
        {activeTab === "artifacts" && <ArtifactsList artifacts={artifacts} />}
        {activeTab === "console" && <ConsoleLogs sandboxId={sandbox?.id} />}
        {activeTab === "verification" && (
          <VerificationReportView
            report={artifacts.find((a) => a.type === "verification_report")?.data?.report ?? null}
          />
        )}
      </div>
    </div>
  );
}

// ===== Preview Frame =====

interface PreviewFrameProps {
  sandbox?: any;
  progress: { id: string; label: string; status: string }[];
  phase?: string;
}

function PreviewFrame({ sandbox, progress, phase }: PreviewFrameProps) {
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
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-8">
        <div className="text-lg font-medium mb-3">No live preview yet</div>
        <div className="text-sm">
          <div className="font-medium mb-1">Current phase: {phase || "init"}</div>
          <ul className="space-y-1">
            {progress.map((step) => (
              <li key={step.id} className="flex items-center gap-2">
                <span>{step.status === "complete" ? "✓" : step.status === "error" ? "✗" : "○"}</span>
                <span>{step.label}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
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
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; path: string } | null>(null);
  const [creating, setCreating] = useState<{ parentPath: string; name: string } | null>(null);

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

  useEffect(() => {
    const handleClick = () => setContextMenu(null);
    if (contextMenu) {
      window.addEventListener("click", handleClick);
      return () => window.removeEventListener("click", handleClick);
    }
  }, [contextMenu]);

  const handleCreateFile = async (parentPath: string, name: string) => {
    if (!sandbox?.id || !name) return;
    const newPath = parentPath ? `${parentPath}/${name}` : name;
    try {
      await api.createEntry(sandbox.id, { type: "file", path: newPath, content: "" });
      await onRefreshTree();
      onOpenFile(newPath);
    } catch (err) {
      console.error("Failed to create file:", err);
    }
  };

  const handleRenameEntry = async (oldPath: string) => {
    if (!sandbox?.id) return;
    const newName = prompt("New name:", oldPath.split("/").pop());
    if (!newName) return;
    const parent = oldPath.split("/").slice(0, -1).join("/");
    const newPath = parent ? `${parent}/${newName}` : newName;
    try {
      await api.renameEntry(sandbox.id, oldPath, newPath);
      await onRefreshTree();
    } catch (err) {
      console.error("Failed to rename:", err);
    }
  };

  const handleDeleteEntry = async (path: string) => {
    if (!sandbox?.id) return;
    if (!confirm(`Delete ${path}?`)) return;
    try {
      await api.deleteEntry(sandbox.id, path);
      await onRefreshTree();
      if (tabs.find((t) => t.path === path)) onCloseTab(path);
    } catch (err) {
      console.error("Failed to delete:", err);
    }
  };

  const handleDownloadZip = async () => {
    if (!sandbox?.id) return;
    try {
      const resp = await fetch(`/api/files/sandboxes/${sandbox.id}/download`);
      if (!resp.ok) throw new Error("Download failed");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${sandbox.id}.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Failed to download ZIP:", err);
    }
  };

  return (
    <div className="flex h-full">
      <div className="w-56 border-r border-border overflow-y-auto bg-muted/30 flex flex-col">
        <div className="flex items-center justify-between px-2 py-1 border-b border-border">
          <span className="text-xs font-semibold">FILES</span>
          <div className="flex gap-1">
            <button
              onClick={() => setCreating({ parentPath: "", name: "" })}
              className="text-xs hover:bg-muted rounded px-1"
              title="New file"
            >
              +
            </button>
            <button
              onClick={handleDownloadZip}
              className="text-xs hover:bg-muted rounded px-1"
              title="Download as ZIP"
            >
              ↓
            </button>
          </div>
        </div>
        {creating && (
          <div className="px-2 py-1 border-b border-border">
            <input
              autoFocus
              type="text"
              value={creating.name}
              onChange={(e) => setCreating({ ...creating, name: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  handleCreateFile(creating.parentPath, creating.name);
                  setCreating(null);
                }
                if (e.key === "Escape") setCreating(null);
              }}
              onBlur={() => setCreating(null)}
              placeholder="filename.tsx"
              className="w-full px-1 py-0.5 text-xs border border-primary rounded focus:outline-none"
            />
          </div>
        )}
        <FileTreeView
          tree={tree}
          expandedDirs={expandedDirs}
          onToggleDir={toggleDir}
          onSelectFile={onOpenFile}
          onContextMenu={(e, path) => {
            e.preventDefault();
            setContextMenu({ x: e.clientX, y: e.clientY, path });
          }}
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
          <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
            Select a file from the tree
          </div>
        )}
      </div>

      {contextMenu && (
        <div
          className="fixed z-50 bg-background border border-border rounded shadow-md py-1 text-xs w-40"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            onClick={() => {
              handleRenameEntry(contextMenu.path);
              setContextMenu(null);
            }}
            className="block w-full text-left px-3 py-1.5 hover:bg-muted"
          >
            Rename
          </button>
          <button
            onClick={() => {
              handleDeleteEntry(contextMenu.path);
              setContextMenu(null);
            }}
            className="block w-full text-left px-3 py-1.5 hover:bg-muted text-destructive"
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

// ===== File Tree View =====

interface FileTreeViewProps {
  tree: TreeNode[];
  expandedDirs: Set<string>;
  onToggleDir: (path: string) => void;
  onSelectFile: (path: string) => void;
  onContextMenu: (e: React.MouseEvent, path: string) => void;
}

function FileTreeView({
  tree,
  expandedDirs,
  onToggleDir,
  onSelectFile,
  onContextMenu,
}: FileTreeViewProps) {
  const renderNode = (node: TreeNode, depth: number = 0) => {
    const name = node.path.split("/").pop();
    const isExpanded = expandedDirs.has(node.path);

    if (node.type === "directory") {
      return (
        <div key={node.path}>
          <button
            onClick={() => onToggleDir(node.path)}
            onContextMenu={(e) => onContextMenu(e, node.path)}
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
        onContextMenu={(e) => onContextMenu(e, node.path)}
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
      <div className="flex items-center justify-center h-full text-muted-foreground">
        No artifacts yet. Run the pipeline to generate artifacts.
      </div>
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
