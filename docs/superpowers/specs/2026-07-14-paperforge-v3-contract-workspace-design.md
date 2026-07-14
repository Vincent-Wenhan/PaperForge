# PaperForge V3 Contract and Workspace Reliability Design

**Date:** 2026-07-14  
**Scope:** `PaperForge_当前代码复查与404修复方案_v3.md` as the primary review, with the second-round implementation details from `PaperForge_深度代码审查与重构实施方案_v2_代码增强版.md` applied where they do not conflict.

## Goal

Turn the current PaperForge prototype into a reliable, state-recoverable coding workspace: a valid Run URL must open without a workspace 404, one snapshot must hydrate the Run, SSE must resume from a durable cursor, tool status must reflect real outcomes, the generated app must remain editable without a sandbox, and the UI must expose those states consistently.

## Confirmed current gaps

The review was checked against the current `main` code and a live TestClient reproduction:

1. `GET /api/approvals?run_id=...` returns FastAPI 404 because only the resolve route exists.
2. The existing on-disk SQLite database predates `messages.public_id`; API message insertion fails until migrations add the column.
3. `/state` returns storage-shaped approvals, metadata-only artifacts, an arbitrary sandbox row, and an in-memory event cursor.
4. The Run page and `ChatPanel` both hydrate the same Run; `ChatPanel` reconnects whenever the `currentRun` object changes.
5. The frontend does not pass the snapshot cursor to `SSEClient`, and one `seenSeqs` set is reused across Runs.
6. Cancellation only calls `Task.cancel()`; the persisted Run status can remain `running`.
7. Approval waiting is only backed by an in-process `asyncio.Event`.
8. The phase allow-list blocks valid post-preview actions; repair/restart actions are not connected to the orchestrator.
9. Sandbox and app file APIs duplicate path logic; sandbox directory operations and new-content size checks are incorrect, while the UI still uses only sandbox paths.
10. Library and Settings response contracts are incomplete; PDF validation and browser download behavior are weak.
11. PDF parsing still truncates the first 80,000 characters; verifier acceptance is not a real runtime/browser check.
12. Changes, Tests, selected Run state, dark Monaco, and user-visible error feedback are incomplete.

The following existing protections are retained: capability data is already present in the planner prompt, the generator already validates its current allow-list and fixed npm scripts, BuildRunner no longer uses the old `time_ns()` expression, backend events are persisted first, and Composer already contains the basic optimistic rollback and single-submit lock.

## Design decisions

### 1. One Run session contract

`GET /api/runs/{run_id}/state` is the only workspace hydration request. Its public response is:

```text
run: RunView
messages: MessageView[]
artifacts: ArtifactView[]       # structured artifacts include data
sandbox: SandboxView | null     # latest by created_at
pending_approvals: ApprovalView[]
tasks: TaskView[]
event_cursor: integer           # max persisted seq for this run
```

The backend owns DTO normalization. Storage names (`id`, `tool_name`) never leak into the frontend approval contract (`approval_id`, `tool`). The frontend owns one `useRunSession(runId)` lifecycle: snapshot first, hydrate only if the Run ID is still current, then connect SSE with `after_seq=event_cursor`. `ChatPanel` becomes a renderer and does not open a second state/SSE subscription.

### 2. Durable event stream and single reducer

SQLite remains the source of truth for event sequence allocation and replay. `run_events(run_id, seq)` stays unique. The server registers the live queue before taking the replay upper bound, replays database rows through that bound, advances the local cursor for every replayed row, and ignores live events at or below that cursor. Queue overflow emits `stream.gap` so the frontend rehydrates.

`SSEClient.connect(runId, afterSeq)` resets its run-local cursor and deduplication state. Every event is applied through one `applyRunEvent` reducer so snapshot, replay, and live delivery produce the same Zustand state transitions.

### 3. Real tool outcomes and artifact prerequisites

The existing `ToolResult.status` is the source of truth. Handlers return `SUCCEEDED`, `FAILED`, or `BLOCKED` based on actual work; `ok` remains a computed compatibility field. Phase is a progress hint, not a permanent lock. Tool execution uses prerequisites derived from the current Run artifacts and sandbox:

```text
compose_capabilities -> capability_card
plan_product         -> capability_card or composition
generate_nextjs_app  -> prd
verify_app           -> nextjs_app
repair_app           -> nextjs_app + verification_report
run_in_sandbox       -> nextjs_app
restart_sandbox      -> sandbox
stop_sandbox         -> sandbox
```

`finish` ends the current task but leaves the Run conversationally usable. A new user message can create a new Task against the same Run and existing artifacts.

### 4. Durable cancellation and approval truth

Cancellation updates the Run and current Task to `cancelled`, emits `run.status.changed` and `run.cancelled`, and awaits task completion. The orchestrator explicitly handles `asyncio.CancelledError` and does not rely on `except Exception`.

The approval row is the source of truth. The in-process Event remains a low-latency wake-up, but the orchestrator waits by polling the persisted row with a bounded timeout, marks timed-out rows `expired`, and treats a resolved row as authoritative even if the registry was recreated. The approval list endpoint and `/state` make refresh recovery reliable; a process restart with no in-memory orchestrator does not claim to resume a lost coroutine.

### 5. App artifact owns the workspace

The `nextjs_app` artifact metadata resolves the app directory. App-based workspace endpoints are the frontend's primary path and validate that the artifact belongs to the current Run when a Run context is available. Sandbox endpoints remain a compatibility surface and share the same safe path rules. Both APIs allow directories, validate file extensions only for files, reject traversal/blocked segments, and enforce the size of the incoming UTF-8 content.

Sandbox management is obtained from the application-level manager when available, with a shared storage-scoped fallback for tests and tool execution. Routes and orchestrator handlers no longer create unrelated manager instances for the same application lifecycle.

### 6. Evidence-preserving paper parsing and layered verification

PDF parsing extracts page strings, chunks them without discarding the tail, maps each chunk to evidence-bearing partial facts, and reduces those facts into one `CapabilityCard`. Evidence page numbers are preserved or filled from the source chunk when the provider omits them. A compact single-page input still follows the same page-aware path.

Verification keeps the existing workspace/static/build layers, records the actual build environment and fallback reason, and replaces raw keyword-only coverage with structured acceptance results when PRD criteria are present. Browser smoke remains an optional execution layer controlled by available dependencies; absence is reported as a failed/degraded runtime check rather than as a successful preview.

### 7. UI states mirror backend truth

The Run workspace keeps its shell and sidebar mounted during errors. It displays typed API errors with a user message, endpoint, and retry action. Sidebar rows receive a selected Run ID and are patched from Run events. Preview readiness is separate from sandbox `running`: only `preview.ready` creates a ready preview state. Code uses the app artifact even when no sandbox exists. Save/restart/rename/upload/download failures use the existing toast provider. Monaco selects `vs-dark` or `vs-light` from `useTheme`.

The existing six workbench tabs remain the stable surface. The Changes tab is upgraded to show file-level changes when revision data exists and otherwise labels tool activity as activity; the Tests tab renders all available static/build/runtime/acceptance results without claiming that a running container is a ready page.

## Data and interface changes

### Storage migrations

`Storage._init_db()` adds missing legacy columns without deleting data:

- `messages.public_id TEXT UNIQUE`
- `messages.status TEXT NOT NULL DEFAULT 'completed'`
- `messages.parts TEXT`
- any event/task columns required by the current schema

Existing rows receive deterministic public IDs derived from their numeric IDs. New streaming messages use the same public ID in SQLite and SSE. Approval expiration is an atomic status transition from `pending` to `expired`.

### Backend endpoints

- `GET /api/approvals` with `run_id` and `status` filters, normalized `ApprovalView` response.
- `POST /api/approvals/{approval_id}/resolve` returns the normalized updated approval and emits the resolution event.
- `GET /api/runs/{run_id}/state` returns the complete normalized snapshot described above.
- `POST /api/runs/{run_id}/cancel` persists cancellation and waits for the task manager.
- `POST /api/sandboxes` resolves an app artifact ID; legacy `app_path` remains accepted only as a compatibility path with root validation.
- App workspace endpoints enforce run/artifact ownership where the route has a Run context.
- `GET /api/library/{paper_id}` returns both `paper` and `capability_card`; upload enforces a 50 MiB bound and `%PDF-` signature.
- `GET /api/settings` returns the model-specific read-only runtime DTO and explicitly labels configuration as environment-controlled.

### Frontend modules

- `web/lib/contracts.ts`: public response normalization and typed API errors.
- `web/lib/run-events.ts`: one event reducer/registration boundary.
- `web/lib/useRunSession.ts`: snapshot/SSE lifecycle keyed only by `runId`.
- `web/lib/store.ts`: Run-isolated reset, task/session fields, preview readiness, and sidebar Run patches.
- `web/lib/api.ts`: cursor-aware SSE, typed errors, blob download helper, and app-workspace methods.

## Verification strategy

Every behavior change is implemented with a failing test first, then the smallest production change:

1. Backend contract tests cover approvals list/resolve, normalized state, migrations on a legacy database, cancellation, expired approvals, safe file directories/content limits, library PDF validation, and settings DTOs.
2. Orchestrator tests cover artifact prerequisites, blocked planner, failed verify/sandbox, repair dispatch, post-preview actions, task creation/phase updates, and cancellation.
3. Event/storage tests cover monotonic sequences after manager recreation, replay/live dedup, public streaming message IDs, and `stream.gap`.
4. Frontend tests cover cursor connection, Run switch isolation, no reconnect on status patch, single submit, typed API errors, app workspace without sandbox, preview readiness, selected Run row, download click, and dark Monaco.
5. A browser smoke test is added when the project can install Playwright; it creates or opens a Run, asserts no workspace 404, verifies the composer and Preview tab, and captures failed console/network requests.
6. Fresh verification runs Python tests, frontend Vitest, frontend production build, and targeted lint/type checks for changed files. Existing unrelated lint debt is reported separately unless a touched file is corrected.

## Acceptance criteria

### Reliability and recovery

- Any existing or newly created valid Run URL opens without `/api/approvals` 404.
- Optional artifact/approval data cannot white-screen the workspace.
- Refresh restores messages, structured artifacts, latest sandbox, pending approvals, tasks, and event cursor.
- SSE starts after the snapshot cursor, does not duplicate events, and replays from SQLite after manager recreation.
- A cancelled Run is not left in `running`.

### Agent and workspace

- Failed verification and not-ready sandbox never advance to `verified` or `preview_ready`.
- A post-preview user message can repair/reverify/restart/stop without a permanent phase lock.
- Repair loop is callable through the orchestrator and persists its latest report.
- Code tree/read/write/create/rename/delete works without a sandbox and accepts directories.
- Incoming file content over the limit is rejected before writing.

### Product quality and UI

- Library detail returns capability-card data and PDF download triggers a browser download.
- Settings displays real model/runtime values and read-only semantics.
- Parser preserves later pages with page evidence; verification exposes real type/lint/build/runtime outcomes.
- Sidebar selection/title/status, typed errors/retry, preview readiness, dark editor, and operation toasts reflect the backend state.
- All Python and frontend tests plus production build pass at the final verification point.

## Deliberately bounded deployment work

The current repository does not include a production reverse-proxy or DNS configuration. This implementation adds the preview route contract, preserves upgrade-related headers where FastAPI/httpx can support them, and makes preview readiness explicit. A hostname-based WebSocket gateway, Playwright browser execution in a deployed sandbox, and full revision/diff persistence are isolated behind typed fields and reported as unavailable when their runtime dependency is absent; they are not faked as successful behavior.
