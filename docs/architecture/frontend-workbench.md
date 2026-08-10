# Frontend Workbench

The adaptive workbench replaces the old fixed 42/58 split.

## Workbench modes

`workbenchMode` is one of:

- `closed` — chat only; preview hidden.
- `peek` — preview peeks open on file/artifact activity; user can dismiss.
- `open` — preview panel visible and resizable.

A `workbenchPinnedClosed` flag lets the user pin the workbench closed; while
pinned, `preview.ready` no longer force-opens it (doc 16.3).

`inferWorkbenchMode(eventType, current, pinnedClosed)` decides transitions
(see `web/lib/run-events.ts`):

- `preview.ready` → `open` (unless pinned).
- `artifact.created` / `file.changed` → `closed` becomes `peek`.

## State

- Zustand holds both the server snapshot and the stream overlay. A future
  phase may split server state into TanStack Query and keep Zustand for
  ephemeral UI + stream (doc 22.3); not a prerequisite for streaming.
- `ui-slice` carries tab, workbench mode, sidebar, draft, scroll state.

## Streaming UX

- `MessageView` is memoized so only in-flight messages re-render.
- Message deltas are buffered and flushed on a `requestAnimationFrame`
  (see realtime protocol).
- Smart scroll: auto-follow until the user scrolls up; a "jump to latest"
  button reappears when they're off bottom (doc 23.11).
