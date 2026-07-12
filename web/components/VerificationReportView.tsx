"use client";

import { useAppStore } from "@/lib/store";

interface VerificationReportViewProps {
  report: any;
  onJumpToFile?: (path: string, line?: number, column?: number) => void;
}

interface ErrorLocation {
  path: string;
  line?: number;
  column?: number;
}

function parseErrorLocation(error: string): ErrorLocation | null {
  const match = error.match(/([^\s]+?):(\d+)(?::(\d+))?/);
  if (!match) return null;
  const path = match[1];
  if (!/\.[a-zA-Z0-9]+$/.test(path)) return null;
  return {
    path,
    line: match[2] ? parseInt(match[2], 10) : undefined,
    column: match[3] ? parseInt(match[3], 10) : undefined,
  };
}

export function VerificationReportView({
  report,
  onJumpToFile,
}: VerificationReportViewProps) {
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
  const typeErrors: string[] = report.type_errors || [];
  const lintErrors: string[] = report.lint_errors || [];
  const securityIssues: string[] = report.security_issues || [];
  const prdCoverage = report.prd_coverage || {};
  const mockRealBoundary = report.mock_real_boundary || {};
  const fixSuggestions: string[] = report.fix_suggestions || [];

  const totalIssues =
    buildErrors.length +
    typeErrors.length +
    lintErrors.length +
    securityIssues.length;

  const handleAskFix = () => {
    const errSummary = [
      ...buildErrors.slice(0, 2),
      ...typeErrors.slice(0, 2),
      ...lintErrors.slice(0, 2),
    ].join("; ");
    setComposerPrefill(
      `Please fix the following issues:\n${errSummary}${
        fixSuggestions.length > 0
          ? `\n\nSuggested fixes:\n${fixSuggestions.slice(0, 3).join("\n")}`
          : ""
      }`,
    );
  };

  const renderError = (error: string, idx: number) => {
    const location = onJumpToFile ? parseErrorLocation(error) : null;
    if (location) {
      return (
        <li key={idx} className="font-mono text-xs break-all">
          <button
            onClick={() =>
              onJumpToFile?.(location.path, location.line, location.column)
            }
            className="text-left hover:underline text-primary"
            title={`Jump to ${location.path}${
              location.line ? `:${location.line}` : ""
            }`}
          >
            {error}
          </button>
        </li>
      );
    }
    return (
      <li key={idx} className="font-mono text-xs break-all">
        {error}
      </li>
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
        <div className="text-sm space-y-0.5">
          <div>
            Build: {report.build_succeeded ? "✓" : "✗"}
          </div>
          <div>
            Ready: {report.ready_for_preview ? "✓" : "✗"}
          </div>
          {report.build_duration_ms && (
            <div className="text-xs text-muted-foreground">
              Build: {(report.build_duration_ms / 1000).toFixed(1)}s
            </div>
          )}
        </div>
      </div>

      {totalIssues === 0 && (
        <div className="p-3 bg-green-50 dark:bg-green-950/30 text-green-800 dark:text-green-200 rounded text-sm">
          ✓ All checks passed
        </div>
      )}

      {buildErrors.length > 0 && (
        <Section
          title="Build Errors"
          items={buildErrors}
          variant="error"
          renderItem={renderError}
        />
      )}

      {typeErrors.length > 0 && (
        <Section
          title="Type Errors"
          items={typeErrors}
          variant="error"
          renderItem={renderError}
        />
      )}

      {lintErrors.length > 0 && (
        <Section
          title="Lint Errors"
          items={lintErrors}
          variant="warning"
          renderItem={renderError}
        />
      )}

      {securityIssues.length > 0 && (
        <Section
          title="Security Issues"
          items={securityIssues}
          variant="error"
          renderItem={renderError}
        />
      )}

      {Object.keys(prdCoverage).length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1">
            PRD Coverage
          </h4>
          <ul className="text-sm space-y-0.5">
            {Object.entries(prdCoverage).map(([feature, status]) => (
              <li key={feature} className="flex items-center gap-2">
                <span>{status === "implemented" ? "✓" : status === "partial" ? "◐" : "○"}</span>
                <span>{feature}</span>
                <span className="text-xs text-muted-foreground">({String(status)})</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {Object.keys(mockRealBoundary).length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1">
            Mock / Real Boundary
          </h4>
          <ul className="text-sm space-y-0.5">
            {Object.entries(mockRealBoundary).map(([key, value]) => (
              <li key={key}>
                <span className="font-mono text-xs">{key}:</span>{" "}
                <span className="text-xs">{String(value)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {fixSuggestions.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1">
            Fix Suggestions
          </h4>
          <ul className="text-sm list-disc list-inside space-y-0.5">
            {fixSuggestions.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}

      {totalIssues > 0 && (
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

function Section({
  title,
  items,
  variant,
  renderItem,
}: {
  title: string;
  items: string[];
  variant: "error" | "warning";
  renderItem?: (error: string, idx: number) => React.ReactNode;
}) {
  const colorClass =
    variant === "error"
      ? "text-red-700 dark:text-red-300"
      : "text-amber-700 dark:text-amber-300";
  return (
    <div>
      <h4 className={`text-xs font-semibold uppercase mb-1 ${colorClass}`}>
        {title} ({items.length})
      </h4>
      <ul className="text-sm list-disc list-inside space-y-0.5">
        {items.map((e, i) =>
          renderItem ? renderItem(e, i) : (
            <li key={i} className="font-mono text-xs break-all">
              {e}
            </li>
          ),
        )}
      </ul>
    </div>
  );
}
