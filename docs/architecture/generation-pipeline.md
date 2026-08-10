# Generation Pipeline

`Paper → Product` end-to-end.

## Stages

1. **Parse** (`parse_paper`, PaperParser) — extracts a capability card JSON
   from the uploaded PDF.
2. **Compose** (`compose_capabilities`, Composer) — combines one or more cards
   into a distinct set of innovation points (a composition).
3. **Plan** (`plan_product`, ProductPlanner) — produces a PRD V2: features
   with stable ids + priorities, and executable acceptance criteria (every
   `must` feature requires at least one).
4. **Generate** (`generate_nextjs_app`, NextjsGenerator) — writes a
   multi-file Next.js app into a workspace, one revision per logical edit,
   validating the app manifest and file content against the plan.
5. **Verify** (`verify_app`, Verifier) — layered checks (see verification).
6. **Sandbox** (`run_in_sandbox`) — boots a Docker container and serves a live
   preview.

## Follow-up

Because resources are durable (`prd`, `workspace`, `sandbox`), a follow-up
user message patches the existing workspace directly instead of restarting
the pipeline from the paper parse.

## Artifacts

Each stage writes a typed artifact (capability card, composition, prd,
verification report, app/workspace) recorded in `artifacts` and surfaced as
`artifact.created` / `artifact.updated` events.
