"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";

type Tab = "preview" | "code" | "console" | "verification";

export function PreviewPanel() {
  const sandbox = useAppStore((s) => s.sandbox);
  const [tab, setTab] = useState<Tab>("preview");
  const [tree, setTree] = useState<any[]>([]);
  const [currentFile, setCurrentFile] = useState("");
  const [fileContent, setFileContent] = useState("");
  const [logs, setLogs] = useState<string[]>([]);

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
          <ConsoleLogs logs={logs} />
        )}
        {tab === "verification" && (
          <VerificationReportView sandboxId={sandbox?.id} />
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
        <textarea
          value={fileContent}
          onChange={(e) => onContentChange(e.target.value)}
          className="flex-1 w-full p-2 font-mono text-xs resize-none focus:outline-none"
          placeholder="Select a file from the tree"
        />
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

function ConsoleLogs({ logs }: { logs: string[] }) {
  return (
    <div className="h-full overflow-y-auto p-2 font-mono text-xs">
      {logs.length === 0 ? (
        <div className="text-muted-foreground">No logs yet</div>
      ) : (
        logs.map((line, i) => <div key={i}>{line}</div>)
      )}
    </div>
  );
}

function VerificationReportView({ sandboxId }: { sandboxId?: string }) {
  return (
    <div className="p-4">
      <h3 className="font-semibold mb-3">Verification Report</h3>
      {!sandboxId ? (
        <p className="text-muted-foreground text-sm">
          Generate and verify an app to see the report.
        </p>
      ) : (
        <p className="text-sm">Sandbox: {sandboxId}</p>
      )}
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-full text-muted-foreground">
      {message}
    </div>
  );
}
