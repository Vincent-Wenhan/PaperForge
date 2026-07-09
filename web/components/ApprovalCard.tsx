"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Approval } from "@/lib/store";

interface Props {
  approval: Approval;
  onResolved?: (approvalId: string, approved: boolean) => void;
}

export function ApprovalCard({ approval, onResolved }: Props) {
  const [resolved, setResolved] = useState<"approved" | "rejected" | null>(
    approval.status === "pending" ? null : (approval.status as "approved" | "rejected")
  );
  const [busy, setBusy] = useState(false);

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

  const stateLabel = resolved
    ? resolved === "approved"
      ? "Approved"
      : "Rejected"
    : "Pending";

  return (
    <div className="border border-amber-400/60 bg-amber-50 dark:bg-amber-950/30 rounded-lg p-3 my-2">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-semibold text-amber-900 dark:text-amber-200">
          Approval required: {approval.tool}
        </div>
        <div className="text-xs text-amber-700 dark:text-amber-300">{stateLabel}</div>
      </div>
      <pre className="text-xs bg-white dark:bg-black/40 border border-border rounded p-2 mb-2 overflow-x-auto">
        {JSON.stringify(approval.args, null, 2)}
      </pre>
      {!resolved && (
        <div className="flex gap-2">
          <button
            onClick={() => handle(true)}
            disabled={busy}
            className="px-3 py-1.5 text-xs font-medium bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
          >
            Approve
          </button>
          <button
            onClick={() => handle(false)}
            disabled={busy}
            className="px-3 py-1.5 text-xs font-medium bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
          >
            Reject
          </button>
        </div>
      )}
    </div>
  );
}
