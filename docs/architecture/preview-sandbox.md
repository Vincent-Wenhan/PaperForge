# Preview / Sandbox

How a generated app gets served to the browser.

## Docker strategy

- Generations run in `node:20-alpine` containers managed by
  `DockerSandboxManager`.
- Each run gets its own container and an allocated `preview_port`.
- `sandbox.started` / `sandbox.error` / `preview.ready` events drive the
  frontend preview state.

## Preview proxy

- A single shared `httpx.AsyncClient` (keepalive pool) proxies all sandbox
  requests (doc 18.2).
- The proxy is **streaming**: upstream bytes are relayed via
  `StreamingResponse(upstream.aiter_raw(), ..., background=BackgroundTask(upstream.aclose))`
  (doc 18.3), so large preview responses don't buffer in memory.
- Upstream host is `127.0.0.1` (never `localhost`) to avoid IPv6/`::1` mismatches.

## Security boundaries

- The preview iframe runs with `sandbox="allow-scripts allow-forms
  allow-modals allow-popups"` and `referrerPolicy="no-referrer"` (doc 18.1).
- Preview is served from an isolated origin so app code can't reach the
  PaperForge API or other runs' storage (see
  [ADR 0005](../adr/0005-preview-origin-isolation.md)).
- Logs stream in-band as `sandbox.log.delta` events instead of polling.

## Task lease recovery

Startup reconciles stale task leases so a "running" UI with a dead worker
recovers to a queued/idle state (doc 21.2).
