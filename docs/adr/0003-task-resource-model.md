# ADR 0003 — Task Resource Model

- **Status:** accepted
- **Date:** 2026-08-10

## Context

The original pipeline always restarted from the paper on every turn, wasting
time and re-parsing on follow-ups. There was no notion of a queued request or
of "what does this tool need before it may run".

## Decision

Introduce a durable **task** (one user turn) with a per-run queue
(start / queue / interrupt) and a **step** granularity reported through
`ProgressReporter`. `check_tool_prerequisites(tool, WorkspaceState)` gates
tools on durable resources (`paper`, `prd`, `workspace`, `sandbox`).

## Consequences

- Follow-ups patch the existing workspace without re-parsing.
- Queue/interrupt gives the user control over a busy agent.
- Steps give visible granular progress instead of a single spinner.
- Leases must be reconciled on startup to avoid stuck "running" states.
