# Realtime Protocol

How message text and events flow from the LLM provider to the browser.

## Duplex summary

1. User posts a message to `POST /api/runs/{run_id}/messages`.
2. The orchestrator starts a per-run serialized task (queue/interrupt modes).
3. Provider output is streamed through `StreamWriter` (server coalescing +
   durable checkpoint), which emits `RunEventEnvelope` v1 over SSE.
4. The browser receives a single `onmessage` payload, dedups by `seq`, applies
   via the `run-events.ts` reducer, and concatenates deltas batched on a
   `requestAnimationFrame`.

## Envelope v1

```jsonc
{
  "version": 1,
  "id": "evt_...",
  "seq": 42,
  "run_id": "run_...",
  "task_id": "task_...",
  "type": "message.delta",
  "ts": 1720000000000,
  "payload": { "message_id": "msg_1", "delta": "text" }
}
```

`seq` is a per-run monotonic cursor. A client that sees a gap (`event.seq >
lastSeq + 1`) rehydrates from `GET /api/runs/{id}/state` rather than trusting
the stream (doc 14.4). Unknown event types are `ignored`, never a hydration.

## Server coalescing (StreamWriter)

- `flush_interval_s` (default 40 ms) + `min_flush_chars` bound how often raw
  provider chunks become `message.delta` SSE events.
- `checkpoint_interval_s` (default 250 ms) overwrites the durable message
  content so a reload mid-stream recovers without duplicate text.

## Provider streaming

All providers expose `stream_events()` yielding `ProviderStreamEvent`
(text / tool call / done / error). A streamed tool call is accumulated until
its `args` are complete before dispatch, so an Anthropic tool call is never
lost partway.

## Client

- `SSEClient` — single `onmessage`, dedup by `seq`, bounded memory.
- `stream-buffer.ts` — rAF batching so N deltas per frame become one React set.
- `useRunSession` — hydrate on connect, rehydrate on gap.

## Metrics targets

See doc 24. Provider delta → SSE yield p95 < 100 ms; SSE → visible render
p95 < 50 ms; 0 duplicated characters on reconnect.
