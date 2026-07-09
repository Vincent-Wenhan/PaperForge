"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { ConsoleLogs } from "./ConsoleLogs";
import { VerificationReportView } from "./VerificationReportView";

const MonacoEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.default), {
  ssr: false,
  loading: () => <div className="p-4 text-muted-foreground">Loading editor...</div>,
});

type Tab = "preview" | "code" | "console" | "verification";

export function PreviewPanel() {
  const sandbox = useAppStore((s) => s.sandbox);
  const [tab, setTab] = useState<Tab>("preview");
  const [tree, setTree] = useState<any[]>([]);
  const [currentFile, setCurrentFile] = useState("");
  const [fileContent, setFileContent] = useState("");
  const [report, setReport] = useState<any>(null);

  useEffect(() => {
    if (!sandbox) return;
    api.getFileTree(sandbox.id).then((resp) => setTree(resp.tree || []));
  }, [sandbox]);

  const openFile = async (path: string) => {
    if (!sandbox) return;
    const resp = await api.readFile(sandbox.id, path);
    setCurrentFile(path);
    setFileContent(resp.content);
  };

  const saveFile = async () => {
    if (!sandbox || !currentFile) return;
    await api.writeFile(sandbox.id, currentFile, fileContent);
  };

  return (
    <div className="flex-1 flex flex-col">
      <div className="flex border-b border-border">
        {(["preview", "code", "console", "verification"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm border-b-2 ${
              tab === t
                ? "border-primary font-medium"
                : "border-transparent text-muted-foreground"
            }`}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-hidden">
        {tab === "preview" && (
          <PreviewFrame sandboxId={sandbox?.id} />
        )}
        {tab === "code" && (
          <CodeEditor
            tree={tree}
            currentFile={currentFile}
            fileContent={fileContent}
            onOpenFile={openFile}
            onSaveFile={saveFile}
            onContentChange={setFileContent}
          />
        )}
        {tab === "console" && (
          <ConsoleLogs sandboxId={sandbox?.id} />
        )}
        {tab === "verification" && (
          <VerificationReportView report={report} />
        )}
      </div>
    </div>
  );
}

function PreviewFrame({ sandboxId }: { sandboxId?: string }) {
  if (!sandboxId) {
    return <EmptyState message="No sandbox running" />;
  }
  return (
    <iframe
      src={api.getPreviewUrl(sandboxId)}
      className="w-full h-full border-0"
      title="Preview"
    />
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

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-full text-muted-foreground">
      {message}
    </div>
  );
}
