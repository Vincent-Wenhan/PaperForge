# ADR 0002 — Provider Stream Events

- **Status:** accepted
- **Date:** 2026-08-10

## Context

Different providers (OpenAI, Anthropic, OpenAI-compatible) exposed
incompatible streaming shapes, and Anthropic's tool calls could be lost when
`args` arrived across multiple chunks.

## Decision

All providers implement `stream_events()` yielding a normalized
`ProviderStreamEvent` (`text` / `tool_call` / `done` / `error`). Tool calls are
accumulated until their `args` are complete before dispatch. The orchestrator
consumes only this abstraction.

## Consequences

- One streaming code path regardless of provider.
- Tool streaming regression (Anthropic) is fixed at the provider boundary and
  covered by a unit test.
- Backfilling a new provider means implementing `stream_events()` only.
