"use client";

import { useAppStore } from "@/lib/store";

interface VerificationReportViewProps {
  report: any;
}

export function VerificationReportView({ report }: VerificationReportViewProps) {
  const setComposerPrefill = useAppStore((s) => s.setComposerPrefill);

  if (!report) {
    return (
      <div className="p-4 text-muted-foreground">
        Run verify_app to see the verification report.
      </div>
    );
  }

  const scorePct = Math.round((report.overall_score || 0) * 100);
  const buildErrors: string[] = report.build_errors || [];
  const securityIssues: string[] = report.security_issues || [];
  const hasIssues = buildErrors.length > 0 || securityIssues.length > 0;

  const handleAskFix = () => {
    const errSummary = buildErrors.slice(0, 3).join("; ");
    setComposerPrefill(
      `Please fix the following build errors:\n${errSummary}`,
    );
  };

  return (
    <div className="p-4 space-y-4">
      <div>
        <h3 className="font-semibold text-lg">Verification Report</h3>
        <p className="text-sm text-muted-foreground">
          App: {report.app_id || "unknown"}
        </p>
      </div>

      <div className="flex items-center gap-4">
        <div className="text-3xl font-bold">{scorePct}%</div>
        <div className="text-sm">
          <div>
            Build: {report.build_succeeded ? "✓" : "✗"}
          </div>
          <div>
            Ready: {report.ready_for_preview ? "✓" : "✗"}
          </div>
        </div>
      </div>

      {buildErrors.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">
            Build Errors
          </h4>
          <ul className="text-sm list-disc list-inside">
            {buildErrors.map((e: string, i: number) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {securityIssues.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">
            Security Issues
          </h4>
          <ul className="text-sm list-disc list-inside">
            {securityIssues.map((s: string, i: number) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}

      {hasIssues && (
        <button
          onClick={handleAskFix}
          className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded hover:opacity-90"
        >
          Ask PaperForge to fix
        </button>
      )}
    </div>
  );
}
