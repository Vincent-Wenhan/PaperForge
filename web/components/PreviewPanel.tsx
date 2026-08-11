"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { ConsoleLogs } from "./ConsoleLogs";
import { useToast } from "@/lib/toast";
import { CodeEditor, buildNestedTree } from "./workbench/CodeEditor";
import { PreviewFrame } from "./workbench/PreviewFrame";
import { ChangesList } from "./workbench/ChangesList";
import { TestsTab } from "./workbench/TestsTab";
import { ArtifactsList } from "./workbench/ArtifactsList";
import { EditorTab, TreeNode } from "./workbench/types";

type Tab = "preview" | "code" | "changes" | "tests" | "artifacts" | "logs";

const WORKBENCH_TABS: { id: Tab; label: string }[] = [
  { id: "preview", label: "Preview" },
  { id: "code", label: "Code" },
  { id: "changes", label: "Changes" },
  { id: "tests", label: "Tests" },
  { id: "artifacts", label: "Artifacts" },
  { id: "logs", label: "Logs" },
];

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
