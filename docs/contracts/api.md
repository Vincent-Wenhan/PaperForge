# API

The FastAPI surface, grouped by resource prefix.

| prefix | purpose |
|---|---|
| `/api/runs` | create/list/get/patch/archive/restore/delete/cancel runs, messages, run state, events (SSE), papers |
| `/api/runs/{run_id}/tasks` | task queue + phase/status |
| `/api/library` | paper upload/list/get/pdf/cards |
| `/api/sandboxes` | sandbox lifecycle (start/stop/restart) |
| `/api/preview` | preview status + streaming proxy (`/api/preview/{sandbox_id}/`) |
| `/api/files` | sandbox file tree/read/write/create/rename/delete |
| `/api/apps` | workspace file tree/edit + revisions/download |
| `/api/artifacts` | artifact list/get/rename/delete/download |
| `/api/approvals` | list + resolve approvals |
| `/api/settings` | runtime settings |
| `/api/health` | liveness |

The OpenAPI schema at `/openapi.json` is the source of truth for machine
consumption; `npm run api:types` regenerates the TS bindings from it
(`web/lib/api/schema.d.ts`).

SSE lives at `/api/runs/{run_id}/events?after_seq=<cursor>` — see
[run events](run-events.md).
