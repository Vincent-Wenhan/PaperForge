"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Approval } from "@/lib/store";

interface Props {
  approval: Approval;
  onResolved?: (approvalId: string, approved: boolean) => void;
}

const TOOL_LABELS: Record<string, string> = {
  generate_nextjs_app: "Generate Next.js app",
  run_in_sandbox: "Start sandbox preview",
  parse_paper: "Parse paper",
  compose_capabilities: "Compose capabilities",
  plan_product: "Plan product",
  verify_app: "Verify app",
};

function extractTargetPath(args: Record<string, any>): string | null {
  if (!args) return null;
  return args.app_path || args.target_path || args.path || args.output_path || null;
}

function extractStepLabel(tool: string): string {
  return TOOL_LABELS[tool] || tool;
}

export function ApprovalCard({ approval, onResolved }: Props) {
  const [resolved, setResolved] = useState<"approved" | "rejected" | null>(
    approval.status === "pending" ? null : (approval.status as "approved" | "rejected")
  );
  const [busy, setBusy] = useState(false);
  const [showPlan, setShowPlan] = useState(false);

  const handle = async (approved: boolean) => {
    if (busy || resolved) return;
    setBusy(true);
    try {
      await api.resolveApproval(approval.approval_id, approved);
      setResolved(approved ? "approved" : "rejected");
      onResolved?.(approval.approval_id, approved);
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(false);
    }
  };

  const stepLabel = extractStepLabel(approval.tool);
  const targetPath = extractTargetPath(approval.args);

  return (
    <div className="border border-amber-400/60 bg-amber-50 dark:bg-amber-950/30 rounded-lg p-4 my-3 max-w-[720px]">
      <div className="flex items-start justify-between mb-2">
        <div>
          <div className="text-sm font-semibold text-amber-900 dark:text-amber-200">
            PaperForge wants to {stepLabel.toLowerCase()}
          </div>
          {targetPath && (
            <div className="mt-1 text-xs text-amber-800 dark:text-amber-300 font-mono break-all">
              Target: {targetPath}
            </div>
          )}
        </div>
        <div className="text-xs text-amber-700 dark:text-amber-300">
          {resolved === "approved" ? "Approved" : resolved === "rejected" ? "Rejected" : "Pending"}
        </div>
      </div>

      {showPlan && (
        <pre className="text-xs bg-white dark:bg-black/40 border border-border rounded p-2 mb-2 overflow-x-auto max-h-48 overflow-y-auto">
          {JSON.stringify(approval.args, null, 2)}
        </pre>
      )}

      <div className="flex gap-2 mt-2">
        {!resolved && (
          <>
            <button
              onClick={() => setShowPlan(!showPlan)}
              disabled={busy}
              className="px-3 py-1.5 text-xs font-medium border border-amber-400 text-amber-800 dark:text-amber-200 rounded hover:bg-amber-100 dark:hover:bg-amber-900/50 disabled:opacity-50"
            >
              {showPlan ? "Hide plan" : "Review plan"}
            </button>
            <button
              onClick={() => handle(false)}
              disabled={busy}
              className="px-3 py-1.5 text-xs font-medium bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
            >
              Reject
            </button>
            <button
              onClick={() => handle(true)}
              disabled={busy}
              className="px-3 py-1.5 text-xs font-medium bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
            >
              {busy ? "Approving..." : "Approve"}
            </button>
          </>
        )}
        {resolved === "approved" && (
          <span className="px-3 py-1.5 text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200 rounded">
            Approved
          </span>
        )}
        {resolved === "rejected" && (
          <span className="px-3 py-1.5 text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200 rounded">
            Rejected
          </span>
        )}
      </div>
    </div>
  );
}
