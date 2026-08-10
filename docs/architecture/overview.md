# Architecture Overview

The current architecture has evolved from the original linear pipeline into a
durable, task-based agent runtime. This document is the entry point into the
architecture subtree.

## System shape

```text
FastAPI (api/) ──┬── Orchestrator loop (paperforge/orchestrator/)
                 ├── Storage (paperforge/storage/)  SQLite (WAL) + filesystem
                 ├── Sub-agents as tools (paperforge/agents/)
                 ├── LLM abstraction (paperforge/llm/)
                 └── Sandbox (paperforge/sandbox/) Docker

Next.js (web/) ── Zustand store + SSE client
```

## Key docs

- [Realtime protocol](realtime-protocol.md) — SSE envelopes, StreamWriter,
  provider streaming, client rAF batching.
- [Task / workspace model](task-workspace-model.md) — run queue, steps,
  resource gate, SafeWorkspacePolicy, durable leases.
- [Generation pipeline](generation-pipeline.md) — parse → compose → PRD V2 →
  multi-file workspace generation.
- [Verification pipeline](verification-pipeline.md) — layered verification.
- [Preview / sandbox](preview-sandbox.md) — Docker strategy, preview proxy.
- [Frontend workbench](frontend-workbench.md) — adaptive workbench modes.

## Contracts

- [Run events](../contracts/run-events.md)
- [PRD V2](../contracts/prd-v2.md)
- [Workspace plan](../contracts/workspace-plan.md)
- [API](../contracts/api.md)

## Decisions

- [ADR index](../adr/) — durable run events, provider stream events, task
  resource model, safe workspace policy, preview origin isolation.

## Historical reviews

- [2026-07 reviews](../reviews/2026-07/) — superseded recommendations already
  landed in code.
