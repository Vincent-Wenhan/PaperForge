"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { ConsoleLogs } from "./ConsoleLogs";
import { VerificationReportView } from "./VerificationReportView";
import { ArtifactCard } from "./ArtifactCard";

const MonacoEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.default), {
  ssr: false,
  loading: () => <div className="p-4 text-muted-foreground">Loading editor...</div>,
});

type Tab = "preview" | "artifacts" | "code" | "console" | "verification";

export function PreviewPanel() {
  const sandbox = useAppStore((s) => s.sandbox);
  const artifacts = useAppStore((s) => s.artifacts);
  const currentRun = useAppStore((s) => s.currentRun);
  const activeTab = useAppStore((s) => s.activeTab);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const [tree, setTree] = useState<any[]>([]);
  const [currentFile, setCurrentFile] = useState("");
  const [fileContent, setFileContent] = useState("");

  useEffect(() => {
    if (!sandbox) return;
    api.getFileTree(sandbox.id).then((resp) => setTree(resp.tree || []));
  }, [sandbox]);

  // Derive progress from real artifacts, sandbox, and verification reports.
  // Never use run.phase as a source of truth — it lies.
  const capability = artifacts.find((a) => a.type === "capability_card");
  const prd = artifacts.find((a) => a.type === "prd");
  const app = artifacts.find((a) => a.type === "nextjs_app");
  const verification = artifacts.find((a) => a.type === "verification_report");

  const report = verification?.data?.report ?? verification?.data ?? null;

  const previewReady = Boolean(sandbox?.id) && sandbox?.status === "running";

  const progress = [
    { id: "capability", label: "Capability card", status: capability ? "complete" : "pending" },
    { id: "prd", label: "PRD", status: prd ? "complete" : "pending" },
    { id: "app", label: "App generated", status: app ? "complete" : "pending" },
    {
      id: "verified",
      label: "Build verified",
      status: report?.build_succeeded
        ? "complete"
        : verification
          ? "error"
          : "pending",
    },
    { id: "preview", label: "Live preview", status: previewReady ? "complete" : "pending" },
  ];

  const tabs: Tab[] = ["preview", "artifacts", "code", "console", "verification"];

  return (
    <div className="flex-1 flex flex-col">
      <div className="flex border-b border-border">
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setActiveTab(t)}
            className={`px-4 py-2 text-sm border-b-2 capitalize ${
              activeTab === t
                ? "border-primary font-medium"
                : "border-transparent text-muted-foreground"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-hidden">
        {activeTab === "preview" && (
          <PreviewFrame sandboxId={sandbox?.id} progress={progress} phase={currentRun?.phase} />
        )}
        {activeTab === "artifacts" && <ArtifactsList artifacts={artifacts} />}
        {activeTab === "code" && (
          <CodeEditor
            tree={tree}
            currentFile={currentFile}
            fileContent={fileContent}
            onOpenFile={openFile}
            onSaveFile={saveFile}
            onContentChange={setFileContent}
          />
        )}
        {activeTab === "console" && <ConsoleLogs sandboxId={sandbox?.id} />}
        {activeTab === "verification" && <VerificationReportView report={report} />}
      </div>
    </div>
  );

  async function openFile(path: string) {
    if (!sandbox) return;
    const resp = await api.readFile(sandbox.id, path);
    setCurrentFile(path);
    setFileContent(resp.content);
  }

  async function saveFile() {
    if (!sandbox || !currentFile) return;
    await api.writeFile(sandbox.id, currentFile, fileContent);
  }
}

interface ProgressItem {
  id: string;
  label: string;
  status: "complete" | "pending" | "error";
}

function PreviewFrame({
  sandboxId,
  progress,
  phase,
}: {
  sandboxId?: string;
  progress: ProgressItem[];
  phase?: string;
}) {
  if (!sandboxId) {
    const hasAnyArtifact = progress.some((p) => p.status === "complete");
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-8">
        <div className="text-lg font-medium mb-3">No live preview yet</div>
        <div className="text-sm">
          <div className="font-medium mb-1">
            Current phase: {phase || "init"}
          </div>
          <ul className="space-y-1">
            {progress.map((step) => (
              <li key={step.id} className="flex items-center gap-2">
                <span>
                  {step.status === "complete"
                    ? "✓"
                    : step.status === "error"
                      ? "✗"
                      : "○"}
                </span>
                <span>{step.label}</span>
              </li>
            ))}
          </ul>
          {!hasAnyArtifact && (
            <div className="mt-3 text-xs">
              Attach a paper and ask PaperForge to productize it.
            </div>
          )}
        </div>
      </div>
    );
  }
  return (
    <iframe
      src={api.getPreviewUrl(sandboxId)}
      className="w-full h-full border-0"
      title="Preview"
    />
  );
}

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

function CodeEditor({
  tree,
  currentFile,
  fileContent,
  onOpenFile,
  onSaveFile,
  onContentChange,
}: any) {
  return (
    <div className="flex h-full">
      <div className="w-56 border-r border-border overflow-y-auto bg-muted/30">
        <FileTree tree={tree} onSelect={onOpenFile} />
      </div>
      <div className="flex-1 flex flex-col">
        <div className="flex items-center justify-between px-3 py-1 border-b border-border">
          <span className="text-xs font-mono">{currentFile || "(no file)"}</span>
          <button
            onClick={onSaveFile}
            disabled={!currentFile}
            className="text-xs px-2 py-1 bg-primary text-primary-foreground rounded disabled:opacity-50"
          >
            Save
          </button>
        </div>
        {currentFile ? (
          <MonacoEditor
            height="100%"
            language={getLanguage(currentFile)}
            value={fileContent}
            onChange={(value) => onContentChange(value || "")}
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
    </div>
  );
}

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

function FileTree({ tree, onSelect }: any) {
  const renderNode = (node: any, depth = 0) => {
    const padding = { paddingLeft: `${depth * 12 + 8}px` };
    if (node.type === "directory") {
      return (
        <div key={node.path} style={padding} className="py-1 text-xs">
          {node.path.split("/").pop()}/
        </div>
      );
    }
    return (
      <button
        key={node.path}
        style={padding}
        onClick={() => onSelect(node.path)}
        className="w-full text-left py-1 text-xs hover:bg-accent"
      >
        {node.path.split("/").pop()}
      </button>
    );
  };
  return <div>{tree.map((node: any) => renderNode(node))}</div>;
}
