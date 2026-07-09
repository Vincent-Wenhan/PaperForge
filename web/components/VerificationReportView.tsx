"use client";

interface VerificationReportViewProps {
  report: any;
}

export function VerificationReportView({
  report,
}: VerificationReportViewProps) {
  if (!report) {
    return (
      <div className="p-4 text-muted-foreground">
        Run verify_app to see the verification report.
      </div>
    );
  }

  const scorePct = Math.round((report.overall_score || 0) * 100);

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

      {report.build_errors && report.build_errors.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">
            Build Errors
          </h4>
          <ul className="text-sm list-disc list-inside">
            {report.build_errors.map((e: string, i: number) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {report.security_issues && report.security_issues.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">
            Security Issues
          </h4>
          <ul className="text-sm list-disc list-inside">
            {report.security_issues.map((s: string, i: number) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
