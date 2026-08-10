# ADR 0001 — Durable Run Events

- **Status:** accepted
- **Date:** 2026-08-10

## Context

Early versions relied on in-memory / per-connection SSE. A disconnect or a
reload lost the conversation, and the frontend had no way to reconcile state
after a gap.

## Decision

Events are **durable** (persisted to the `events` table) and assigned a
per-run monotonic `seq` cursor. Clients connect with `?after_seq=<cursor>`
and rehydrate from `GET /api/runs/{id}/state` whenever they detect a real
gap.

## Consequences

- Reload mid-stream recovers without duplicate text (partial checkpoint in
  `StreamWriter`).
- Unknown/future event types are ignored rather than forcing a hydration.
- Requires the event store to grow monotonically per run (bounded on the
  client).
