# ADR 0005 — Preview Origin Isolation

- **Status:** accepted
- **Date:** 2026-08-10

## Context

A generated app runs arbitrary JS in the browser. Served on the same origin
as the PaperForge API, it could read other runs' data or the user's session.

## Decision

Preview is served from an isolated origin, and the iframe uses a strict
`sandbox` attribute (`allow-scripts allow-forms allow-modals allow-popups`)
with `referrerPolicy="no-referrer"`. The backend proxies preview traffic
through a shared, streaming HTTP client on `127.0.0.1`.

## Consequences

- App code cannot reach the PaperForge API or cross-run storage.
- Referrer leakage and most browser-based exfiltration are blocked.
- Requires the proxy to properly stream and close upstream connections.
