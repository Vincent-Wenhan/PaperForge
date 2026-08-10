# Task / Workspace Model

From a one-shot linear pipeline to a durable, resumable agent runtime.

## Run queue

Each run serializes messages through a per-run queue with three modes:
`start` (replace a running task), `queue` (run when idle), `interrupt`
(preempt the current turn). A follow-up that arrives while the agent is busy
is queued instead of re-parsing from scratch.

## Tasks and steps

- A **task** is one user turn (a queued request). It carries a goal, phase,
  status, and a durable claim/lease.
- A **step** is a granular work item inside a task (e.g. `codegen`, `build`,
  `test`). `ProgressReporter` creates/updates steps and emits
  `step.started/progress/completed/failed` events, which surface as an inline
  timeline in the UI.
- Stale leases are reconciled on startup so a UI never stays stuck on
  "running" with no worker (doc 21.2).

## Resource gate

`check_tool_prerequisites(tool_name, WorkspaceState)` decides whether a tool
may run based on resources available in durable state (`paper`, `prd`,
`workspace`, `sandbox`, …). This is what lets follow-up edits skip re-parsing:
once a workspace exists, `apply_workspace_patch` / `run_checks` are allowed
without a new `parse_paper` + `plan_product`.

## SafeWorkspacePolicy

All workspace-mutating tools normalize paths against an allowed root
(`SafeWorkspacePolicy`): directory traversal, absolute paths, `node_modules`,
and `.git` are rejected. File patches apply per-revision so every logical edit
is replayed and recoverable.
