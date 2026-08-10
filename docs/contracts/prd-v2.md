# PRD V2

Product model produced by `plan_product` (ProductPlanner).

## Shape

- `features` — stable `id`, `name`, `priority` (`must` / `should` / `could`).
- `acceptance_criteria` — executable criteria bound to a feature:
  `test_kind` (`route` / `text` / `interaction` / `api` / `visual`), target
  `route`, optional `selector`, and an `action` + `expected` value.

## Validation invariant

Every `must`-have feature requires at least one executable acceptance
criterion. The Pydantic model validator rejects a PRD where a `must` feature
has none (see `tests/integration/test_realtime_contract.py` / PRD schema).
This keeps the verification pipeline driven by testable behavior rather than
vague requirements.

## Usage

- `generate_nextjs_app` consumes the PRD + acceptance criteria to produce the
  manifest and app.
- `verify_app` / `run_checks` exercise the criteria against the build.
