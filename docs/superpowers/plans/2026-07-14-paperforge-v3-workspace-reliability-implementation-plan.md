# PaperForge v3 工作区可靠性实施计划

> 本计划以 \`docs/PaperForge_当前代码复查与404修复方案_v3.md\` 为主，结合 v2 中仍未完成的可靠性要求。执行方式：当前主分支 inline execution；每个任务先写回归测试，再实现，再运行针对性验证。

## 目标

完成以下闭环：

- Run 页面只依赖一个可恢复的会话状态契约，不因可选接口 404 或短暂错误白屏。
- Run 状态、消息、审批、任务、沙箱、产物和事件游标来自同一套规范化 DTO。
- 事件持久化到 SQLite，SSE 支持游标重放且不重复、不丢失。
- 取消、审批和阶段推进由数据库事实驱动。
- 代码工作区以 app artifact 为边界，文件 API 正确区分文件与目录并限制输入大小。
- 解析、校验、预览、文库和设置接口满足 v3 的验收条件。
- 前端实现会话 hydration、SSE 增量更新、预览状态和工作区操作，并保留现有兼容接口。

## 任务 1：数据库兼容、DTO 与事件持久化

Files:

- Modify: \`paperforge/storage/db.py\`
- Modify: \`paperforge/orchestrator/events.py\`
- Modify: \`api/routes/runs.py\`
- Modify: \`api/routes/approvals.py\`
- Test: \`tests/test_storage_legacy.py\`
- Test: \`tests/test_run_state_contract.py\`
- Test: \`tests/test_approvals_api.py\`

Steps:

1. Add a legacy SQLite fixture whose \`messages\` table lacks \`public_id\`, \`status\`, and \`parts\`; assert \`Storage\` initialization migrates it and \`add_message\` succeeds.
2. Add message normalization and artifact/approval/run view helpers; preserve raw storage methods for existing callers.
3. Add DB-backed approval listing and atomic pending resolution; return \`409\` for a repeated or already resolved decision.
4. Make the event manager persist events through the active storage, carry \`task_id\`, and read history by database cursor.
5. Make \`GET /api/runs/{run_id}/state\` return normalized run/messages/artifacts/approvals/tasks/sandbox/event cursor data and use the latest sandbox.
6. Add \`GET /api/approvals?run_id=...\` and return the normalized approval DTO from resolve.
7. Run the focused backend tests and the existing backend suite.

## 任务 2：任务取消、审批与可恢复编排循环

Files:

- Modify: \`paperforge/orchestrator/tasks.py\`
- Modify: \`paperforge/orchestrator/approvals.py\`
- Modify: \`paperforge/orchestrator/loop.py\`
- Modify: \`paperforge/orchestrator/tools.py\`
- Modify: \`paperforge/storage/db.py\`
- Test: \`tests/test_task_cancel.py\`
- Test: \`tests/test_approval_checkpoint.py\`
- Test: \`tests/test_orchestrator_workflow.py\`

Steps:

1. Add tests proving cancellation persists terminal run status and an event, and a later run does not resume a cancelled run.
2. Add tests proving an approval can be resolved through the API and the loop wakes from the database truth.
3. Add a bounded cancel wait, checkpoint persistence, and recovery of the last durable phase/event cursor.
4. Replace irreversible phase-only gating with artifact prerequisites and add \`build_and_repair\`, sandbox restart, and stop dispatch paths.
5. Reuse one sandbox manager per run and persist structured tool failure codes/data.
6. Ensure tool handlers return explicit next phases only after successful prerequisites and keep failed verification/preview recoverable.
7. Run focused tests plus the complete backend suite.

## 任务 3：安全的 app 工作区与文件 API

Files:

- Modify: \`api/routes/files.py\`
- Modify: \`api/routes/apps.py\`
- Modify: \`paperforge/orchestrator/tools.py\`
- Modify: \`paperforge/storage/db.py\`
- Test: \`tests/test_file_api_contract.py\`
- Test: \`tests/test_app_workspace_contract.py\`

Steps:

1. Add tests for directory listing, nested directory creation, incoming content-size rejection, invalid entry types, traversal rejection, and app artifact ownership.
2. Split safe path resolution into path and file variants; validate entry type before filesystem mutation.
3. Enforce maximum size on incoming content rather than existing file size and reject oversized writes consistently for files and app artifacts.
4. Make generation output use a server-owned app artifact/workspace; accept artifact IDs in tool/API contracts while retaining safe legacy compatibility where needed.
5. Add artifact-to-run ownership checks and prevent cross-run app access.
6. Run focused tests and the full backend suite.

## 任务 4：解析分块、验证分层与预览可观测性

Files:

- Modify: \`paperforge/agents/paper_parser.py\`
- Modify: \`paperforge/agents/verifier.py\`
- Modify: \`paperforge/sandbox/build_runner.py\`
- Modify: \`paperforge/sandbox/docker_runner.py\`
- Modify: \`paperforge/orchestrator/tools.py\`
- Test: \`tests/test_parser_chunking.py\`
- Test: \`tests/test_verifier_layers.py\`
- Test: \`tests/test_preview_workflow.py\`

Steps:

1. Add tests for page-aware extraction, bounded map chunks, reduce output, structured verifier layers, and preview degraded/running/error states.
2. Implement page parsing with page markers, chunk map calls, and a reduce call that returns stable structured sections.
3. Expose verifier layer results and PRD coverage, then wire \`build_and_repair\` into the tool workflow with bounded repair attempts.
4. Make BuildRunner report environment/degraded/fallback details and use the shared sandbox manager.
5. Keep Docker calls bounded and preserve safe local fallback diagnostics.
6. Run focused tests and the complete backend suite.

## 任务 5：统一前端契约与 API 错误

Files:

- Modify: \`web/lib/api.ts\`
- Modify: \`web/lib/types.ts\`
- Add: \`web/lib/contracts.ts\`
- Test: \`web/__tests__/api-contract.test.ts\`

Steps:

1. Add tests for structured \`ApiError\`, normalized state response, cursor-aware SSE URL, and app artifact/file API helpers.
2. Implement one typed API error parser that preserves status, code, detail, and raw payload.
3. Add shared RunSession, Approval, Task, Sandbox, Artifact, Preview, and event contracts.
4. Make \`getRunState\` the canonical hydration endpoint and make approval/download helpers use the real backend routes.
5. Extend SSE client connection with an event cursor and reset per-run deduplication.
6. Keep compatibility aliases only where existing callers still require them.

## 任务 6：前端 session hydration、SSE reducer 与 store

Files:

- Modify: \`web/lib/store.ts\`
- Add: \`web/lib/run-events.ts\`
- Add: \`web/lib/useRunSession.ts\`
- Modify: \`web/components/ChatPanel.tsx\`
- Modify: \`web/app/runs/[id]/page.tsx\`
- Test: \`web/__tests__/run-session.test.ts\`
- Test: \`web/__tests__/run-events.test.ts\`

Steps:

1. Add tests that hydrate once per \`runId\`, apply monotonically increasing events, retain artifacts/approvals/tasks, and do not reconnect when the run object changes only by status.
2. Add store fields/actions for preview, tasks, sandbox, last cursor, and session error.
3. Implement an event reducer that updates the smallest affected state and triggers rehydration for unknown or gap events.
4. Implement \`useRunSession(runId)\` with one hydration request, one cursor-aware SSE connection, cleanup, and typed error state.
5. Remove the ChatPanel effect dependency on the whole run object and make the page use the session hook as the single source of truth.
6. Run frontend unit tests and type/build checks.

## 任务 7：代码工作区、预览、侧栏与文库体验

Files:

- Modify: \`web/components/PreviewPanel.tsx\`
- Modify: \`web/components/Sidebar.tsx\`
- Modify: \`web/app/library/[paperId]/page.tsx\`
- Modify: \`api/routes/library.py\`
- Modify: \`api/routes/settings.py\`
- Modify: \`web/app/settings/page.tsx\`
- Test: \`web/__tests__/preview-panel.test.tsx\`
- Test: \`web/__tests__/library-settings.test.tsx\`

Steps:

1. Add tests for app-artifact code browsing, preview status rendering, browser PDF download, capability-card details, and settings field display.
2. Make PreviewPanel use the app workspace first, expose loading/error/empty states, and show real preview status instead of treating a running sandbox as a passed test.
3. Add a structured changes view and make restart/stop state updates visible.
4. Make Sidebar selection and download actions reflect the active run and trigger a browser download.
5. Validate PDF size/content type/magic bytes/empty input and return capability-card data in paper details.
6. Expand settings DTO from runtime config and label the page as read-only runtime configuration.
7. Run frontend tests, build, and focused backend library tests.

## 任务 8：页面可靠性与可访问性回归

Files:

- Modify: \`web/app/runs/[id]/page.tsx\`
- Modify: \`web/components/Sidebar.tsx\`
- Modify: \`web/components/ChatPanel.tsx\`
- Modify: \`web/components/PreviewPanel.tsx\`
- Test: \`web/__tests__/RunRow.test.tsx\`
- Test: \`web/__tests__/streaming.test.tsx\`

Steps:

1. Add tests for selected run semantics, keyboard submit behavior, attachment rollback, reconnect cursor behavior, and non-blocking optional-panel failures.
2. Preserve the shell while hydration or optional artifacts fail; show actionable inline errors.
3. Add \`aria-current\`, keyboard-visible controls, and stable empty/error/loading states.
4. Verify that chat submit is single-flight and that run status changes do not recreate the SSE session.
5. Run the complete frontend test suite.

## 任务 9：集成验证与提交推送

Files:

- Modify only files required by failing verification.

Steps:

1. Run \`python -m pytest tests/ -q\`.
2. Run \`npm test -- --run\` and \`npm run build\` in \`web\`.
3. Run targeted Ruff on touched Python files; fix introduced errors without broad unrelated churn.
4. Run API regression checks for \`POST /api/runs\`, \`GET /api/runs/{id}/state\`, \`GET /api/approvals\`, SSE replay, cancel, files/apps, library PDF, and settings.
5. Inspect \`git diff --check\`, review the complete diff, and verify no secrets or generated artifacts are included.
6. Commit implementation with a focused message, then push \`main\` to \`origin\`.
7. Report commit, push result, test evidence, and any intentionally preserved untracked user documents.

## 风险与边界

- Existing public API compatibility is preserved where a safe translation is possible; cross-run access and unsafe filesystem operations remain hard failures.
- Docker availability is environment-dependent. The implementation reports degraded/local fallback state explicitly; it does not claim Docker preview success when Docker is unavailable.
- Browser E2E is added only if the repository already has a runnable browser harness; otherwise unit/API regression evidence is the acceptance boundary for this pass.

