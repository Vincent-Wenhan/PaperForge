# Run Events Contract

Semantic event types carried in `RunEventEnvelope` v1 over SSE.

## Envelope

See [realtime protocol](../architecture/realtime-protocol.md) for the wire
format and cursor semantics.

## Event types

| type | payload | effect |
|---|---|---|
| `message.started` | `message_id` | create streaming assistant message |
| `message.delta` | `message_id`, `delta` | append text (client rAF-batched) |
| `message.completed` | `message_id`, `content` | finalize message |
| `message.failed` | `message_id`, `error` | mark failed |
| `tool.call` / `tool.result` | name/args | debug timeline |
| `run.started` / `run.finished` / `run.error` | — | run lifecycle + running state |
| `run.status.changed` / `run.updated` | — | run field patches |
| `task.phase.changed` | `task_id`, `phase` | task phase + run phase |
| `step.started` | `step_id`, `task_id`, `kind`, `title` | new step |
| `step.progress` | `step_id`, `percent?`, `detail?` | step progress |
| `step.completed` | `step_id`, `summary?` | step done |
| `step.failed` | `step_id`, `error?` | step failed |
| `approval.requested` | `approval_id`, `tool`, `args` | HITL prompt |
| `approval.resolved` | `approval_id`, `approved` | HITL resolution |
| `artifact.created` / `artifact.updated` | `artifact_id`, ... | workbench peek |
| `sandbox.started` / `sandbox.error` | — | sandbox lifecycle |
| `preview.ready` | `sandbox_id`, `preview_url` | auto-open workbench |
| `sandbox.log.delta` | `sandbox_id`, `stream`, `text` | incremental log |
| `stream.gap` | — | force rehydrate |

## Frontend contract

`web/lib/run-events.ts` reduces each event into the Zustand store. Rules:

- `seq` lower/equal to the cursor → `duplicate` (ignore).
- `seq` gap → `gap` (rehydrate).
- unknown type → `unknown` / `ignored` (never rehydrate, doc 23.7).

Tests live in `web/lib/__tests__/run-events.test.ts`.
