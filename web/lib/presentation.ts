// User-facing status text for tasks and runs (doc 12.3). Raw status strings
// like "waiting_approval" are never shown to the user; the mapper produces
// product-level copy instead.
const TASK_STATUS_LABEL: Record<string, string> = {
  queued: "Preparing",
  running: "Working",
  waiting_approval: "Needs attention",
  waiting_tool: "Needs attention",
  waiting_input: "Needs attention",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

const RUN_STATUS_LABEL: Record<string, string> = {
  active: "Active",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  error: "Error",
  cancelled: "Cancelled",
};

export function taskStatusLabel(status: string | undefined | null): string {
  if (!status) return "Preparing";
  return TASK_STATUS_LABEL[status] ?? status;
}

export function runStatusLabel(status: string | undefined | null): string {
  if (!status) return "Active";
  return RUN_STATUS_LABEL[status] ?? status;
}
