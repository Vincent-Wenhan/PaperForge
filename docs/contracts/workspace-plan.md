# Workspace Plan

The delivery mechanism that turns a PRD into a multi-file app.

## Role

`WorkspacePlan` is the intermediate contract between `plan_product` and
`generate_nextjs_app`: a list of logical file operations (create / patch /
revision) that together realize the product without invalidating the manifest.

Each logical edit is a revision, so the app can be rolled back or replayed.

## SafeWorkspacePolicy

All workspace operations normalize paths through `SafeWorkspacePolicy`, which
rejects:

- directory traversal (`../`)
- absolute paths (`/etc/...`)
- dependency-manager dirs (`node_modules/...`)
- VCS internals (`.git/...`)

A patch is `apply_workspace_patch(root, patch, policy)`; protected files and
unsafe paths raise `ValueError`. See
[tests/schemas/workspace_policy_check.py](../../tests/schemas/workspace_policy_check.py).
