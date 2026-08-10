# ADR 0004 — Safe Workspace Policy

- **Status:** accepted
- **Date:** 2026-08-10

## Context

Agents write arbitrary files into a generated app. Path traversal, absolute
paths, and dependency/VCS internals could escape the workspace or corrupt the
project.

## Decision

All workspace-mutating tools normalize paths via `SafeWorkspacePolicy`,
rejecting traversal, absolute paths, `node_modules`, and `.git`. File patches
apply per-revision so every logical edit is replayable.

## Consequences

- The model is confined to a bounded writable root.
- Unsafe paths raise `ValueError` and are tested (parametrized path cases).
- Introduces a fixed list of protected path prefixes that must be kept in
  sync with the sandbox layout.
