"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { EmptyState } from "../Skeleton";
import { useTheme } from "@/lib/useTheme";
import { EditorTab, TreeNode } from "./types";

const MonacoEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.default), {
  ssr: false,
  loading: () => <div className="p-4 text-muted-foreground">Loading editor...</div>,
});

export function CodeEditor({
  tree,
  tabs,
  activeTabPath,
  sandbox,
  onOpenFile,
  onCloseTab,
  onSaveFile,
  onContentChange,
  onRefreshTree,
}: {
  tree: TreeNode[];
  tabs: EditorTab[];
  activeTabPath: string | null;
  sandbox?: any;
  onOpenFile: (path: string) => void;
  onCloseTab: (path: string) => void;
  onSaveFile: (path: string) => void;
  onContentChange: (path: string, content: string) => void;
  onRefreshTree: () => Promise<void>;
}) {
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

function FileTreeView({
  tree,
  expandedDirs,
  onToggleDir,
  onSelectFile,
}: {
  tree: TreeNode[];
  expandedDirs: Set<string>;
  onToggleDir: (path: string) => void;
  onSelectFile: (path: string) => void;
}) {
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

export function getLanguage(path: string): string {
  if (path.endsWith(".tsx")) return "typescript";
  if (path.endsWith(".ts")) return "typescript";
  if (path.endsWith(".jsx")) return "javascript";
  if (path.endsWith(".js")) return "javascript";
  if (path.endsWith(".json")) return "json";
  if (path.endsWith(".css")) return "css";
  if (path.endsWith(".md")) return "markdown";
  return "plaintext";
}

export function buildNestedTree(flatTree: any[]): TreeNode[] {
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
