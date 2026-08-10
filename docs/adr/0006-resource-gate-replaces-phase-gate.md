# ADR 0006 — Resource Gate replaces Phase Gate

- **Status:** accepted
- **Date:** 2026-08-11

## Context

The orchestrator historically gated which tools could run per run-phase via
`ALLOWED_TOOLS[RunPhase]`, plus a `PHASE_TRANSITIONS` map. This created a
dual authority with the newer resource gate (`check_tool_prerequisites`),
so a run stuck in `DONE` could not keep editing its workspace, and
every tool had to be re-listed for every phase.

## Decision

Remove `ALLOWED_TOOLS` and `PHASE_TRANSITIONS`. The **resource gate**
(`WorkspaceState` + `check_tool_prerequisites`) is the sole tool-prereq
authority (doc 14). `RunPhase` remains only as a UI-facing progress label,
not a permission gate. `DANGEROUS_TOOLS` still drives HITL approval.

## Consequences

- A completed run can keep editing its workspace without re-parsing.
- Tool permissions no longer drift between phase and resource definitions.
- Status transitions stay under `ToolResult.next_phase` and run status.
