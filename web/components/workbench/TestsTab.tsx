"use client";

import { VerificationReportView } from "../VerificationReportView";

export function TestsTab({
  artifacts,
  sandbox,
  preview,
}: {
  artifacts: any[];
  sandbox?: any;
  preview?: any;
}) {
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
