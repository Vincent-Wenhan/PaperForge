# Verification Pipeline

How a generated app is checked before it ships to the sandbox.

## Layers

1. **Static / structural** — the generated app manifest and entry points are
   validated against the PRD's acceptance criteria (routable/selectable).
2. **Unit-ish** — per-layer checks (parser, verifier) run synchronously.
3. **Sandbox** — the app boots in a container and `verify_app` / `run_checks`
   exercises the acceptance criteria against the live build; results feed a
   `build` / `test` step with a verification report artifact.

Failures are fed back into the repair loop (`build_and_repair`) rather than
aborting the run, so the orchestrator iterates until the checks pass or it
gives up.

## User-visible

Progress shows as inline steps (`codegen`, `build`, `test`, `preview`), and
the final verification report is a downloadable artifact in the workbench.
