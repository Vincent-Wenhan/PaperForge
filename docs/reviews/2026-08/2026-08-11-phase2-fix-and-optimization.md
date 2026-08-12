# PaperForge 第二阶段实现、修复与深度优化方案

> **审查日期：2026-08-11**  
> **审查对象：** `Vincent-Wenhan/PaperForge` 当前 GitHub `main` 分支  
> **目标：** 不重复已经完成的旧方案，而是针对当前代码中“已经实现 / 半实现 / 未接通 / 明确 Bug / 需要进一步产品化”的部分继续向下落地。  
> **目标体验：** 接近 ChatGPT / Codex 的持续式 Agent Workspace：实时、连续、可观察、可编辑、可验证，而不是一次性论文→App 流水线。  
> **实施原则：** 优先修闭环与 correctness，再做交互收敛，然后做生成质量和 production hardening。

---

# 目录

1. 当前版本总判断  
2. 当前实现状态矩阵  
3. 第一阶段：P0 Integration Closure  
4. P0-1：修复 `ToolContext(task_id=...)` 主链路运行错误  
5. P0-2：真正实现 Workspace Tools，而不是只在 Phase/Resource 表里声明  
6. P0-3：修复 `nextjs_app` 无法恢复为 workspace resource  
7. P0-4：修复 Anthropic Streaming Tool Call 丢失  
8. P0-5：修复 Browser Acceptance 与 PRD V2 契约不一致  
9. 第二阶段：彻底完成 Realtime Pipeline  
10. SSE Envelope V2 与 forward compatibility  
11. 前端 delta batching、稳定渲染与滚动  
12. 第三阶段：从一次性 Pipeline 升级为 Continuous Agent  
13. Run / Task / Workspace 的最终模型  
14. Resource Gate 真正替代 Phase Gate  
15. Queue / Interrupt / Follow-up 的完整实现  
16. Task/Step 可观察执行模型  
17. Approval Policy V2  
18. 第四阶段：Generation V3  
19. WorkspacePlan 与分批代码生成  
20. Context Selection / Dependency Graph  
21. Safe Workspace Patch + Revision  
22. Targeted Repair V2  
23. 第五阶段：Verification V3  
24. Hard Gates 与 readiness 分层  
25. Browser Acceptance Executor V2  
26. Streaming Build/Test Runner  
27. 第六阶段：Conversation / Turn UI 重构  
28. Composer 重构  
29. Turn Projection 与 Inline Steps  
30. Smart Scroll、Markdown Streaming 与渲染性能  
31. 第七阶段：Workbench 深度重构  
32. Adaptive closed / peek / open  
33. 拆分 900 行 `PreviewPanel.tsx`  
34. Changes / Tests / Logs / Artifacts 交互  
35. 第八阶段：前端 State / Type Contract 重构  
36. 第九阶段：Parser / Capability Contract  
37. 第十阶段：Durable Worker / Event Broker / Production Runtime  
38. Preview / Sandbox 安全强化  
39. Observability / SLO  
40. 测试矩阵与核心测试代码  
41. 推荐 PR 顺序  
42. 文件级修改清单  
43. 删除旧路径清单  
44. 最终 Definition of Done  
45. 审查依据

---

# 1. 当前版本总判断

PaperForge 当前不是“重写一遍”的状态，而是进入了一个非常关键的 **Integration Closure（集成收口）** 阶段。

现在的代码里已经存在不少正确的新架构：

```text
StreamWriter
WorkspaceState
ToolSpec / Resource Gate
WorkspacePlan
SafeWorkspacePolicy
PRD V2
durable run_events
event seq / replay
workspace revisions
Browser Smoke
Task model
RunQueue scaffold
```

问题在于，这些新架构有相当一部分还没有成为**唯一主路径**。

当前 repo 里存在明显的“双轨并存”：

```text
新 Resource Gate
+
旧 ALLOWED_TOOLS Phase Gate

新 WorkspacePlan
+
旧一次性大 JSON generation

新 Task
+
旧 RunPhase 作为全局流程状态

新 PRD executable acceptance
+
旧 Browser Smoke executor

新 StreamWriter
+
旧前端逐 event 直接 setState

新 RunQueue scaffold
+
旧 Message API 直接 409

Workspace tool names 已进入 phase/resource 定义
+
Tool definitions / dispatcher 尚未实现

task_id 已传入 Orchestrator ToolContext
+
ToolContext 构造器尚未接收 task_id
```

所以当前最危险的事情不是“缺少更多 abstraction”，而是：

> **继续新增新架构，但旧路径没有删除，导致代码看起来功能越来越多，主流程反而出现接口错位。**

这一轮的核心策略应该是：

```text
先让已有新架构真正跑通
↓
删除旧路径
↓
再提升生成质量和 UI
```

---

# 2. 当前实现状态矩阵

## 2.1 Realtime

| 能力 | 当前状态 | 下一步 |
|---|---|---|
| 后端 LLM streaming | 已实现 | 保留 |
| `StreamWriter` 40ms coalesce | 已实现 | 保留并补测试 |
| 250ms message checkpoint | 已实现 | 保留 |
| Durable `run_events` | 已实现 | 保留 |
| SSE replay / `after_seq` | 已实现 | 保留 |
| SSE forward compatibility | 未完成 | 改统一 envelope |
| 前端 rAF delta batching | 未实现 | P1 |
| Smart stick-to-bottom | 未实现 | P1 |
| 完整 provider-neutral stream | 未实现 | P0/P1 |
| Anthropic streamed tool use | 有 Bug | P0 |

## 2.2 Agent Runtime

| 能力 | 当前状态 | 下一步 |
|---|---|---|
| Task 表 | 已实现 | 保留 |
| ToolContext task 关联 | 接口错位 | **P0** |
| Resource Gate | 半实现 | 去掉 Phase Gate 权威 |
| WorkspaceState | 半实现 | 修 artifact restore |
| Workspace tools | 只声明、未真正注册 | **P0** |
| Queue scaffold | 有 | API 未使用 |
| Interrupt | 未实现产品语义 | P1 |
| Continuous editing | 未实现 | P1 |
| Observable Steps | 未形成完整主链路 | P1 |
| Durable worker | 未实现 | P2 |

## 2.3 Generation / Verification

| 能力 | 当前状态 | 下一步 |
|---|---|---|
| 3-file 限制 | 已删除 | 正确 |
| SafeWorkspacePolicy | 已实现 | 扩展到 repair |
| WorkspacePlan schema | 已实现 | 真正驱动 generation |
| 多文件生成 | 已实现 | 仍为一次大调用 |
| Atomic temp-dir swap | 已实现 | 保留 |
| PRD V2 | 已实现 | 保留 |
| Browser Smoke | 已接入 | executor 有契约 Bug |
| Verification layers | 已实现 | hard gate 仍不正确 |
| Targeted repair | 未实现 | P1 |
| Streaming verification | helper 有、主流程未接 | P1 |

## 2.4 Frontend

| 能力 | 当前状态 | 下一步 |
|---|---|---|
| Chat / Preview split | 已实现 | 仍固定 42/58 |
| Adaptive Workbench | 未实现 | P1 |
| Running 中继续输入 | 未实现 | P1 |
| Queue / Interrupt UI | 未实现 | P1 |
| Optimistic ID reconciliation | 半实现 | public_id 没传 |
| Agent Activity | 有 | 与 turn 脱节 |
| Turn UI | 未实现 | P1 |
| Smart auto-scroll | 未实现 | P1 |
| Stable message key | 未实现 | index key |
| Quick Actions | 旧 demo 风格仍存在 | 删除 |
| PreviewPanel 拆分 | 未实现 | 仍约 900 行 |
| Store slices/types | 未实现 | P2 |

---

# 3. 第一阶段：P0 Integration Closure

第一阶段不要做大的视觉重构。

先把下面这些问题修掉：

```text
1. ToolContext task_id 接口错误
2. Workspace tools 真正注册
3. nextjs_app artifact → WorkspaceState 修复
4. Anthropic tool streaming 修复
5. Browser Acceptance 与 PRD contract 修复
6. 为这些路径补 regression tests
```

这些问题修完以后再做 Continuous Agent，否则前端即使做得像 Codex，底层也会在关键路径上被旧逻辑卡住。

---

# 4. P0-1：修复 `ToolContext(task_id=...)` 主链路运行错误

## 4.1 当前问题

当前 `loop.py` 构造：

```python
ctx = ToolContext(
    run_id=run_id,
    storage=self.storage,
    llm=self.llm,
    emit=emit,
    sandbox_manager=self.sandbox_manager,
    task_id=self.task_id,
)
```

但是当前 `tools.py`：

```python
class ToolContext:
    def __init__(
        self,
        run_id: str,
        storage: Storage,
        llm: LLMClient,
        emit: EventEmitter,
        sandbox_manager: Any | None = None,
    ) -> None:
        ...
```

没有 `task_id`。

这不是设计问题，而是直接的接口 mismatch。

## 4.2 修复

```python
class ToolContext:
    """Context shared by tool handlers in one task execution."""

    def __init__(
        self,
        run_id: str,
        storage: Storage,
        llm: LLMClient,
        emit: EventEmitter,
        sandbox_manager: Any | None = None,
        task_id: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.task_id = task_id

        self.storage = storage
        self.llm = llm
        self.emit = emit

        self._sandbox_manager = (
            sandbox_manager
        )

    def get_sandbox_manager(
        self,
    ) -> Any:
        if self._sandbox_manager is None:
            from paperforge.sandbox.docker_runner import (
                DockerSandboxManager,
            )

            self._sandbox_manager = (
                DockerSandboxManager(
                    storage=self.storage
                )
            )

        return self._sandbox_manager
```

## 4.3 进一步：EventEmitter 也绑定 task_id

现在大多数 EventEmitter convenience wrapper 没有传 `task_id`。

建议改：

```python
class EventEmitter:
    def __init__(
        self,
        run_id: str,
        manager: EventManager,
        task_id: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.manager = manager
        self.task_id = task_id

    async def emit(
        self,
        event_type: str,
        data: Any = None,
        task_id: str | None = None,
    ) -> Event:
        resolved_task_id = (
            task_id
            if task_id is not None
            else self.task_id
        )

        event = Event(
            type=event_type,
            data=data,
            run_id=self.run_id,
            task_id=resolved_task_id,
        )

        await self.manager.broadcast(event)

        return event
```

Orchestrator 中：

```python
emit = EventEmitter(
    run_id=run_id,
    manager=event_manager,
    task_id=task_id,
)
```

这样：

```text
message.delta
tool.call
tool.result
artifact.created
approval.requested
preview.ready
```

默认都带当前 task_id。

这会直接为后面的 **Turn Projection** 打基础。

---

# 5. P0-2：真正实现 Workspace Tools

## 5.1 当前问题

`loop.py` 和 `workspace.py` 已经声明：

```text
inspect_workspace
read_workspace_file
apply_workspace_patch
run_checks
```

但是当前 `TOOL_DEFINITIONS` 没有这些 tool，dispatcher 也没有对应 handler。

因此模型根本不会在 tool schema 中看到它们。

这属于：

```text
权限模型说“可调用”
但 runtime 没实现
```

## 5.2 新增 tool definitions

```python
TOOL_DEFINITIONS.extend([
    ToolDefinition(
        name="inspect_workspace",
        description=(
            "Inspect the current generated app workspace. "
            "Returns a bounded text file tree and the latest revision."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "max_depth": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 6,
                    "default": 4,
                }
            },
            "required": [],
        },
    ),

    ToolDefinition(
        name="read_workspace_file",
        description=(
            "Read one safe text file from the current generated app."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                }
            },
            "required": ["path"],
        },
    ),

    ToolDefinition(
        name="apply_workspace_patch",
        description=(
            "Apply a bounded create/replace/delete patch "
            "inside the current generated app workspace."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                },
                "files": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string"
                            },
                            "operation": {
                                "type": "string",
                                "enum": [
                                    "create",
                                    "replace",
                                    "delete",
                                ],
                            },
                            "content": {
                                "type": "string"
                            },
                        },
                        "required": [
                            "path",
                            "operation",
                        ],
                    },
                },
            },
            "required": [
                "summary",
                "files",
            ],
        },
    ),

    ToolDefinition(
        name="run_checks",
        description=(
            "Run bounded workspace checks such as "
            "typecheck, lint, or build on the current app."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "checks": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "typecheck",
                            "lint",
                            "build",
                        ],
                    },
                    "default": [
                        "typecheck",
                    ],
                }
            },
            "required": [],
        },
    ),
])
```

## 5.3 Workspace resolver 不要每个 handler 自己找 artifact

新增：

```text
paperforge/workspace/resolver.py
```

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkspaceRef:
    app_id: str
    path: Path
    revision_id: str | None = None


def resolve_workspace(
    storage,
    run_id: str,
) -> WorkspaceRef:
    artifacts = storage.list_artifacts(
        run_id
    )

    for artifact in reversed(
        artifacts
    ):
        artifact_type = (
            artifact.get("type")
            or artifact.get(
                "artifact_type"
            )
            or ""
        )

        if artifact_type not in {
            "nextjs_app",
            "app",
            "workspace",
        }:
            continue

        metadata = (
            artifact.get("metadata")
            or {}
        )

        raw_path = (
            artifact.get("path")
            or metadata.get("app_path")
            or metadata.get(
                "workspace_path"
            )
        )

        if not raw_path:
            continue

        path = Path(
            raw_path
        ).resolve()

        if not path.exists():
            continue

        revision = (
            storage.get_latest_workspace_revision(
                run_id=run_id,
                app_id=artifact["id"],
            )
            if hasattr(
                storage,
                "get_latest_workspace_revision",
            )
            else None
        )

        return WorkspaceRef(
            app_id=artifact["id"],
            path=path,
            revision_id=(
                revision["id"]
                if revision
                else None
            ),
        )

    raise ValueError(
        "No generated workspace exists "
        f"for run {run_id}"
    )
```

## 5.4 `inspect_workspace`

```python
IGNORE_NAMES = {
    ".git",
    ".next",
    "node_modules",
    ".previous",
}


def _walk_workspace(
    root: Path,
    *,
    max_depth: int = 4,
    max_entries: int = 300,
) -> list[str]:
    entries: list[str] = []

    def visit(
        current: Path,
        depth: int,
    ) -> None:
        if (
            depth > max_depth
            or len(entries)
            >= max_entries
        ):
            return

        children = sorted(
            current.iterdir(),
            key=lambda path: (
                path.is_file(),
                path.name.lower(),
            ),
        )

        for child in children:
            if child.name in IGNORE_NAMES:
                continue

            relative = child.relative_to(
                root
            )

            entries.append(
                str(relative)
                + (
                    "/"
                    if child.is_dir()
                    else ""
                )
            )

            if child.is_dir():
                visit(
                    child,
                    depth + 1,
                )

            if (
                len(entries)
                >= max_entries
            ):
                break

    visit(root, 0)

    return entries
```

Handler：

```python
async def handle_inspect_workspace(
    args: dict[str, Any],
    ctx: ToolContext,
) -> ToolResult:
    workspace = resolve_workspace(
        ctx.storage,
        ctx.run_id,
    )

    max_depth = min(
        max(
            int(
                args.get(
                    "max_depth",
                    4,
                )
            ),
            1,
        ),
        6,
    )

    files = _walk_workspace(
        workspace.path,
        max_depth=max_depth,
    )

    return ToolResult(
        tool="inspect_workspace",
        status=ToolStatus.SUCCEEDED,
        data={
            "app_id": workspace.app_id,
            "workspace_path": str(
                workspace.path
            ),
            "revision_id": (
                workspace.revision_id
            ),
            "files": files,
        },
        summary=(
            f"Inspected workspace: "
            f"{len(files)} entries."
        ),
    )
```

## 5.5 `read_workspace_file`

```python
TEXT_EXTENSIONS = {
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".css",
    ".scss",
    ".md",
    ".txt",
    ".html",
    ".svg",
}


async def handle_read_workspace_file(
    args: dict[str, Any],
    ctx: ToolContext,
) -> ToolResult:
    workspace = resolve_workspace(
        ctx.storage,
        ctx.run_id,
    )

    policy = SafeWorkspacePolicy()

    relative = policy.normalize(
        str(args["path"])
    )

    target = (
        workspace.path
        / relative
    ).resolve()

    target.relative_to(
        workspace.path.resolve()
    )

    if not target.exists():
        return ToolResult(
            tool="read_workspace_file",
            status=ToolStatus.FAILED,
            code="file_not_found",
            error=(
                f"File does not exist: "
                f"{relative}"
            ),
            retryable=True,
        )

    if not target.is_file():
        return ToolResult(
            tool="read_workspace_file",
            status=ToolStatus.FAILED,
            code="not_a_file",
            error=(
                f"Not a file: {relative}"
            ),
            retryable=True,
        )

    if (
        target.suffix
        and target.suffix
        not in TEXT_EXTENSIONS
    ):
        return ToolResult(
            tool="read_workspace_file",
            status=ToolStatus.BLOCKED,
            code="binary_or_unsupported",
            error=(
                "Only bounded text source files "
                "can be read."
            ),
            retryable=False,
        )

    raw = target.read_text(
        encoding="utf-8"
    )

    # 防止把超大文件塞进 LLM context。
    max_chars = 80_000

    truncated = (
        len(raw) > max_chars
    )

    content = raw[:max_chars]

    return ToolResult(
        tool="read_workspace_file",
        status=ToolStatus.SUCCEEDED,
        data={
            "path": relative,
            "content": content,
            "truncated": truncated,
            "characters": len(raw),
        },
        summary=(
            f"Read {relative}"
            + (
                " (truncated)."
                if truncated
                else "."
            )
        ),
    )
```

## 5.6 `apply_workspace_patch`

建议复用统一 schema：

```python
from typing import Literal
from pydantic import BaseModel


class FilePatch(BaseModel):
    path: str

    operation: Literal[
        "create",
        "replace",
        "delete",
    ]

    content: str | None = None


class WorkspacePatch(BaseModel):
    summary: str
    files: list[FilePatch]
```

安全执行：

```python
def apply_patch(
    workspace_root: Path,
    patch: WorkspacePatch,
    policy: SafeWorkspacePolicy,
) -> list[str]:
    changed: list[str] = []

    total_bytes = sum(
        len(
            (item.content or "")
            .encode("utf-8")
        )
        for item in patch.files
    )

    if (
        total_bytes
        > policy.MAX_PATCH_BYTES
    ):
        raise ValueError(
            "Patch exceeds size limit"
        )

    for item in patch.files:
        relative = policy.normalize(
            item.path
        )

        target = (
            workspace_root
            / relative
        ).resolve()

        target.relative_to(
            workspace_root.resolve()
        )

        if item.operation == "delete":
            if target.exists():
                if target.is_dir():
                    raise ValueError(
                        "Directory deletion "
                        "is not allowed."
                    )
                target.unlink()

        else:
            content = (
                item.content or ""
            )

            policy.validate_content(
                content
            )

            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            target.write_text(
                content,
                encoding="utf-8",
            )

        changed.append(relative)

    return changed
```

Handler：

```python
async def handle_apply_workspace_patch(
    args: dict[str, Any],
    ctx: ToolContext,
) -> ToolResult:
    workspace = resolve_workspace(
        ctx.storage,
        ctx.run_id,
    )

    patch = WorkspacePatch.model_validate(
        args
    )

    policy = SafeWorkspacePolicy()

    # 先 snapshot before state。
    before = (
        ctx.storage
        .create_workspace_revision(
            run_id=ctx.run_id,
            app_id=workspace.app_id,
            source="before_patch",
            app_path=str(
                workspace.path
            ),
        )
    )

    try:
        changed = apply_patch(
            workspace.path,
            patch,
            policy,
        )
    except Exception:
        # 可选：restore before revision
        raise

    after = (
        ctx.storage
        .create_workspace_revision(
            run_id=ctx.run_id,
            app_id=workspace.app_id,
            source="agent_patch",
            app_path=str(
                workspace.path
            ),
        )
    )

    for path in changed:
        await ctx.emit.emit(
            "file.changed",
            {
                "path": path,
                "revision_id": (
                    after["id"]
                ),
                "summary": (
                    patch.summary
                ),
            },
        )

    return ToolResult(
        tool="apply_workspace_patch",
        status=ToolStatus.SUCCEEDED,
        data={
            "changed_files": changed,
            "before_revision_id": (
                before["id"]
            ),
            "revision_id": (
                after["id"]
            ),
        },
        summary=(
            patch.summary
            or (
                f"Updated "
                f"{len(changed)} file(s)."
            )
        ),
    )
```

## 5.7 Dispatcher 真正注册

```python
TOOL_HANDLERS = {
    "parse_paper": handle_parse_paper,
    "compose_capabilities": (
        handle_compose_capabilities
    ),
    "plan_product": handle_plan_product,
    "generate_nextjs_app": (
        handle_generate
    ),
    "verify_app": handle_verify,
    "build_and_repair": (
        handle_build_and_repair
    ),
    "repair_app": handle_repair,
    "run_in_sandbox": (
        handle_run_in_sandbox
    ),
    "stop_sandbox": (
        handle_stop_sandbox
    ),
    "restart_sandbox": (
        handle_restart_sandbox
    ),

    # 新的持续编辑工具
    "inspect_workspace": (
        handle_inspect_workspace
    ),
    "read_workspace_file": (
        handle_read_workspace_file
    ),
    "apply_workspace_patch": (
        handle_apply_workspace_patch
    ),
    "run_checks": (
        handle_run_checks
    ),

    "finish": handle_finish,
}
```

---

# 6. P0-3：修复 `nextjs_app` 无法恢复为 workspace resource

## 6.1 当前问题

当前 generation 保存：

```text
artifact_type = "nextjs_app"
metadata.app_path = output_dir
```

但 `load_workspace_state()` 只识别：

```python
if atype in {
    "app",
    "workspace",
}:
    state.workspace_path = art.get(
        "path"
    )
```

这会导致：

```text
App 已经生成
↓
WorkspaceState 恢复不到 workspace_path
↓
available_resources()
没有 "workspace"
↓
workspace tools 被 resource gate 拦截
```

## 6.2 修复 loader

```python
def load_workspace_state(
    storage,
    run_id: str,
) -> WorkspaceState:
    papers = storage.list_run_papers(
        run_id
    )

    state = WorkspaceState(
        paper_ids=[
            paper["paper_id"]
            for paper in papers
        ]
    )

    artifacts = (
        storage.list_artifacts(
            run_id
        )
    )

    for artifact in artifacts:
        artifact_type = (
            artifact.get("type")
            or artifact.get(
                "artifact_type"
            )
            or ""
        )

        metadata = (
            artifact.get("metadata")
            or {}
        )

        if (
            artifact_type
            == "composition"
        ):
            state.composition_id = (
                artifact["id"]
            )

        elif artifact_type == "prd":
            state.prd_id = (
                artifact["id"]
            )

        elif artifact_type in {
            "nextjs_app",
            "app",
            "workspace",
        }:
            state.app_id = (
                artifact["id"]
            )

            state.workspace_path = (
                artifact.get("path")
                or metadata.get(
                    "app_path"
                )
                or metadata.get(
                    "workspace_path"
                )
            )

        elif artifact_type in {
            "verification_report",
            "verification",
        }:
            state.verification_report_id = (
                artifact["id"]
            )

    latest_sandbox = (
        storage.get_latest_sandbox(
            run_id
        )
        if hasattr(
            storage,
            "get_latest_sandbox",
        )
        else None
    )

    if latest_sandbox:
        state.sandbox_id = (
            latest_sandbox["id"]
        )

        state.preview_url = (
            latest_sandbox.get(
                "preview_url"
            )
        )

    return state
```

同时修掉当前这个没有意义的写法：

```python
atype.get("id")
if isinstance(atype, dict)
```

因为 `atype` 本身已经被定义成字符串。

---

# 7. P0-4：修复 Anthropic Streaming Tool Call

## 7.1 当前问题

当前 Anthropic：

```python
async with self.client.messages.stream(
    **kwargs
) as stream:
    async for text in stream.text_stream:
        yield Chunk(
            content=text
        )
```

只消费 `text_stream`。

但是 `chat()` 里明确处理：

```text
block.type == "tool_use"
```

因此带 tools 的 native streaming 路径会丢 tool use。

## 7.2 最低风险 Hotfix

在 Provider-neutral event 完成前：

```python
async def stream(
    self,
    model: str,
    messages: list[Message],
    tools: list[
        ToolDefinition
    ] | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> AsyncIterator[Chunk]:

    if tools:
        # correctness > tool-turn token streaming
        response = await self.chat(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if response.content:
            yield Chunk(
                content=response.content
            )

        if response.tool_calls:
            yield Chunk(
                tool_calls=(
                    response.tool_calls
                )
            )

        yield Chunk(
            finish_reason=(
                response.finish_reason
            )
        )

        return

    system, msgs = (
        self._split_messages(
            messages
        )
    )

    kwargs = {
        "model": (
            model
            or self.default_model
        ),
        "system": system,
        "messages": msgs,
        "temperature": temperature,
        "max_tokens": (
            max_tokens or 4096
        ),
    }

    async with (
        self.client.messages.stream(
            **kwargs
        )
    ) as stream:
        async for text in (
            stream.text_stream
        ):
            yield Chunk(
                content=text
            )

    yield Chunk(
        finish_reason="stop"
    )
```

这个 hotfix 应该先 merge。

完整 Provider-normalization 放到第 9 节。

---

# 8. P0-5：修复 Browser Acceptance 与 PRD V2 契约不一致

## 8.1 当前 Bug A：route criterion 用错字段

PRD V2 已经有：

```text
criterion.route
criterion.selector
```

但当前 route/api executor 用：

```python
target = urljoin(
    base_url.rstrip("/") + "/",
    selector or "/",
)
```

这实际上把 selector 当 URL。

应改为：

```python
route = (
    criterion.get("route")
    or "/"
)

target = urljoin(
    base_url.rstrip("/") + "/",
    route.lstrip("/"),
)
```

## 8.2 当前 Bug B：interaction 忽略 `action`

Schema 支持：

```text
none
click
fill
upload
select
```

但当前 interaction 只要有 selector 就执行 click。

应该做真正的 executor。

```python
async def execute_interaction(
    page,
    criterion: dict[str, Any],
    *,
    timeout_ms: int,
) -> dict[str, Any]:
    selector = (
        criterion.get("selector")
    )

    if not selector:
        raise RuntimeError(
            "Interaction criterion "
            "requires selector."
        )

    locator = page.locator(
        selector
    ).first

    await locator.wait_for(
        state="visible",
        timeout=timeout_ms,
    )

    action = (
        criterion.get("action")
        or "none"
    )

    input_value = (
        criterion.get("input_value")
    )

    if action == "none":
        pass

    elif action == "click":
        await locator.click(
            timeout=timeout_ms
        )

    elif action == "fill":
        if input_value is None:
            raise RuntimeError(
                "fill action requires "
                "input_value."
            )

        await locator.fill(
            str(input_value)
        )

    elif action == "select":
        if input_value is None:
            raise RuntimeError(
                "select action requires "
                "input_value."
            )

        await locator.select_option(
            str(input_value)
        )

    elif action == "upload":
        if input_value is None:
            raise RuntimeError(
                "upload action requires "
                "fixture path."
            )

        await locator.set_input_files(
            str(input_value)
        )

    else:
        raise RuntimeError(
            f"Unsupported action: {action}"
        )

    return {
        "selector": selector,
        "action": action,
    }
```

## 8.3 每条 criterion 都应该进入自己的 route

不要只在最开始：

```python
page.goto(base_url)
```

应该：

```python
async def goto_criterion_route(
    page,
    base_url: str,
    criterion: dict[str, Any],
    timeout_ms: int,
) -> str:
    route = (
        criterion.get("route")
        or "/"
    )

    target = urljoin(
        base_url.rstrip("/") + "/",
        route.lstrip("/"),
    )

    await page.goto(
        target,
        wait_until="domcontentloaded",
        timeout=timeout_ms,
    )

    return target
```

## 8.4 `expected` 要按 test kind 解释

不要所有 string 都做“页面全文 contains”。

建议：

```python
async def verify_expected(
    page,
    locator,
    expected: Any,
) -> None:
    if expected is None:
        return

    if expected is True:
        if locator is None:
            raise RuntimeError(
                "Expected visible element "
                "but selector is absent."
            )

        if not await locator.is_visible():
            raise RuntimeError(
                "Expected element "
                "to be visible."
            )

        return

    if expected is False:
        if (
            locator is not None
            and await locator.is_visible()
        ):
            raise RuntimeError(
                "Expected element "
                "not to be visible."
            )

        return

    if isinstance(
        expected,
        str,
    ):
        if locator is not None:
            actual = (
                await locator.inner_text()
            )

            if expected not in actual:
                raise RuntimeError(
                    f"Expected {expected!r} "
                    "not found in element."
                )
        else:
            html = await page.content()

            if expected not in html:
                raise RuntimeError(
                    f"Expected {expected!r} "
                    "not found on page."
                )
```

## 8.5 没有 criteria 不应该叫 passed

当前：

```text
No executable acceptance criteria
→ status="passed"
```

更合理：

```python
return {
    "status": "not_applicable",
    "checks": [],
    "reason": (
        "No executable acceptance "
        "criteria were supplied."
    ),
}
```

因为：

```text
“没有测”
≠
“验收通过”
```

PRD V2 本身应确保 must-have feature 都有 criteria，所以正常 productization flow 不应长期落到这个分支。

---


# 9. 第二阶段：彻底完成 Realtime Pipeline

后端 `StreamWriter` 已经是当前 repo 中比较成熟的一块，不建议重做。

下一步重点是：

```text
1. Provider stream contract 统一
2. SSE transport 去 named-event hardcode
3. event task_id 贯穿
4. 前端 rAF batching
5. unknown event forward-compatible
6. smart auto-scroll
7. streaming performance metrics
```

---

# 10. SSE Envelope V2 与 Forward Compatibility

## 10.1 当前问题

当前 SSE server 会发送：

```text
id: <seq>
event: message.delta
data: {...}
```

前端维护固定：

```ts
const EVENT_TYPES = [
  "message.started",
  "message.delta",
  ...
];
```

并逐个：

```ts
sse.on(eventType, ...)
```

这意味着新增 event 需要同时修改 server/client event registration。

更严重的是当前前端：

```ts
if (
  result === "gap"
  || result === "unknown"
) {
  hydrate();
}
```

这会把“前端暂时不认识的新事件”误认为“流丢失”。

## 10.2 统一 envelope

后端：

```python
def encode_sse(
    event: Event,
) -> str:
    envelope = {
        "version": 2,
        "id": event.id,
        "seq": event.seq,
        "run_id": event.run_id,
        "task_id": event.task_id,
        "type": event.type,
        "ts": event.ts,
        "payload": (
            event.data or {}
        ),
    }

    return (
        f"id: {event.seq}\n"
        "data: "
        + json.dumps(
            envelope,
            ensure_ascii=False,
        )
        + "\n\n"
    )
```

**不再写：**

```text
event: message.delta
```

Browser 只使用默认 `message` event。

## 10.3 前端 `RunStream`

```typescript
export interface RunEvent<
  Payload = unknown
> {
  version: 2;

  id: string;
  seq: number;

  run_id: string;
  task_id?: string | null;

  type: string;
  ts: number;

  payload: Payload;
}


export class RunStream {
  private source:
    | EventSource
    | null = null;

  connect(
    runId: string,
    afterSeq: number,
    onEvent: (
      event: RunEvent
    ) => void,
    onError?: (
      error: Event
    ) => void,
  ) {
    this.disconnect();

    const query =
      afterSeq > 0
        ? `?after_seq=${afterSeq}`
        : "";

    this.source = new EventSource(
      buildUrl(
        `/api/runs/${runId}/events${query}`
      )
    );

    this.source.onmessage = (
      raw
    ) => {
      const event = JSON.parse(
        raw.data
      ) as RunEvent;

      onEvent(event);
    };

    this.source.onerror = (
      event
    ) => {
      onError?.(event);
    };
  }

  disconnect() {
    this.source?.close();
    this.source = null;
  }
}
```

## 10.4 Reducer Result

```typescript
export type ApplyRunEventResult =
  | "applied"
  | "ignored"
  | "duplicate"
  | "gap";
```

```typescript
export function applyRunEvent(
  event: RunEvent,
  runId: string,
): ApplyRunEventResult {
  const store =
    useAppStore.getState();

  if (event.run_id !== runId) {
    return "ignored";
  }

  if (
    event.seq
    <= store.lastSeq
  ) {
    return "duplicate";
  }

  if (
    store.lastSeq > 0
    && event.seq
       > store.lastSeq + 1
  ) {
    return "gap";
  }

  store.setLastSeq(
    event.seq
  );

  store.addDebugEvent(
    event
  );

  switch (event.type) {
    case "message.started":
      // ...
      return "applied";

    case "message.delta":
      // ...
      return "applied";

    case "stream.gap":
      return "gap";

    default:
      // Unknown != missing.
      return "ignored";
  }
}
```

Session：

```typescript
const cursor = await hydrate();

stream.connect(
  runId,
  cursor,
  (event) => {
    const result =
      applyRunEvent(
        event,
        runId,
      );

    if (result === "gap") {
      void hydrate();
    }
  },
);
```

这会让协议可以安全增加：

```text
step.started
step.progress
file.changed
build.log.delta
test.completed
```

而不用担心旧前端反复 full hydration。

---

# 11. 前端 Delta Batching、稳定渲染与滚动

## 11.1 当前问题

后端已经 40ms coalesce，但前端仍然：

```ts
case "message.delta":
  store.appendMessageDelta(...)
```

每个 SSE delta 都直接触发 Zustand update。

当前 store 又：

```text
findIndex
copy messages array
replace message
```

ChatPanel 每次 messages/events 更新都会：

```ts
scrollIntoView({
  behavior: "smooth"
})
```

所以仍存在：

```text
SSE delta
→ Zustand update
→ React tree render
→ Markdown parse
→ smooth scroll
```

## 11.2 `requestAnimationFrame` buffer

```typescript
const pending =
  new Map<string, string>();

let frameId:
  | number
  | null = null;


export function enqueueDelta(
  messageId: string,
  delta: string,
) {
  pending.set(
    messageId,
    (
      pending.get(messageId)
      ?? ""
    ) + delta,
  );

  if (frameId !== null) {
    return;
  }

  frameId = requestAnimationFrame(
    () => {
      const store =
        useAppStore.getState();

      for (
        const [id, text]
        of pending
      ) {
        store.appendMessageDelta(
          id,
          text,
        );
      }

      pending.clear();
      frameId = null;
    }
  );
}


export function flushDeltas() {
  if (frameId !== null) {
    cancelAnimationFrame(
      frameId
    );
    frameId = null;
  }

  const store =
    useAppStore.getState();

  for (
    const [id, text]
    of pending
  ) {
    store.appendMessageDelta(
      id,
      text,
    );
  }

  pending.clear();
}
```

Reducer：

```typescript
case "message.delta": {
  const {
    message_id,
    delta,
  } = event.payload as
    MessageDeltaPayload;

  enqueueDelta(
    message_id,
    delta,
  );

  return "applied";
}

case "message.completed": {
  flushDeltas();

  // complete...
  return "applied";
}
```

## 11.3 Normalized Message Store

如果想进一步解决 `findIndex()`：

```typescript
interface ConversationState {
  messageOrder: string[];

  messagesById:
    Record<
      string,
      Message
    >;
}
```

Append：

```typescript
appendMessageDelta(
  id,
  delta,
) {
  set((state) => {
    const current =
      state.messagesById[id];

    if (!current) {
      return state;
    }

    return {
      messagesById: {
        ...state.messagesById,
        [id]: {
          ...current,
          content:
            current.content
            + delta,
          streaming: true,
          status: "streaming",
        },
      },
    };
  });
}
```

UI：

```typescript
const messages = useMemo(
  () =>
    messageOrder.map(
      (id) =>
        messagesById[id]
    ),
  [
    messageOrder,
    messagesById,
  ],
);
```

第一阶段不必强制 normalized；rAF batching + stable key 已足够明显改善。

## 11.4 Smart Stick-to-Bottom

```typescript
import {
  RefObject,
  useEffect,
  useLayoutEffect,
  useState,
} from "react";


export function useAutoFollow(
  ref:
    RefObject<HTMLDivElement>,
  version: number,
) {
  const [
    follow,
    setFollow,
  ] = useState(true);

  useEffect(() => {
    const node = ref.current;

    if (!node) return;

    const onScroll = () => {
      const distance =
        node.scrollHeight
        - node.scrollTop
        - node.clientHeight;

      setFollow(
        distance < 96
      );
    };

    node.addEventListener(
      "scroll",
      onScroll,
      { passive: true },
    );

    return () => {
      node.removeEventListener(
        "scroll",
        onScroll,
      );
    };
  }, [ref]);

  useLayoutEffect(() => {
    const node = ref.current;

    if (!node || !follow) {
      return;
    }

    // Streaming 时不要 smooth。
    node.scrollTop =
      node.scrollHeight;
  }, [
    version,
    follow,
    ref,
  ]);

  const jumpToLatest = () => {
    const node = ref.current;

    if (!node) return;

    node.scrollTo({
      top: node.scrollHeight,
      behavior: "smooth",
    });

    setFollow(true);
  };

  return {
    follow,
    jumpToLatest,
  };
}
```

UI：

```tsx
{!follow && (
  <button
    onClick={jumpToLatest}
    className="
      absolute
      bottom-24
      left-1/2
      -translate-x-1/2
      rounded-full
      border
      bg-background/95
      px-3 py-1.5
      text-xs
      shadow-sm
      backdrop-blur
    "
  >
    ↓ Jump to latest
  </button>
)}
```

## 11.5 Stable Message Key

当前：

```tsx
key={i}
```

改：

```tsx
<MessageView
  key={
    message.public_id
    ?? message.id
  }
  message={message}
/>
```

## 11.6 Memo 完成消息

```tsx
export const MessageView =
  memo(
    MessageViewImpl,
    (prev, next) => {
      return (
        prev.message.id
          === next.message.id
        && prev.message.content
          === next.message.content
        && prev.message.status
          === next.message.status
      );
    },
  );
```

只让最后一个 streaming assistant message 高频更新。

---

# 12. 第三阶段：从一次性 Pipeline 升级为 Continuous Agent

当前最大产品层问题仍然是：

```text
Run 被当成“一次 pipeline”
```

而不是：

```text
Run = 持久 Thread + Workspace
```

Codex/ChatGPT 风格要求：

```text
第一次：
Productize this paper
→ parse → plan → generate

第二次：
Make sidebar narrower
→ inspect → read → patch → check

第三次：
Add export button
→ inspect → patch → verify

第四次：
Why is this failing?
→ inspect logs → explain
```

不应该每一轮都从：

```text
INIT
```

重新开始。

---

# 13. Run / Task / Workspace 最终模型

## 13.1 Run = Thread

```python
@dataclass
class RunState:
    id: str
    title: str

    status: str

    workspace_app_id:
        str | None

    created_at: str
    updated_at: str
```

Run status 建议只保留 aggregate：

```text
active
running
waiting_user
error
archived
```

不要把：

```text
done
```

理解成“这个 thread 永远不能继续”。

## 13.2 Task = 用户的一次目标

```python
class TaskStatus(
    str,
    Enum,
):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = (
        "waiting_approval"
    )
    WAITING_USER = (
        "waiting_user"
    )
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

```python
class TaskRecord(BaseModel):
    id: str
    run_id: str

    user_message_id: str

    goal: str
    status: TaskStatus

    display_phase:
        str | None = None

    started_at:
        datetime | None = None

    completed_at:
        datetime | None = None
```

## 13.3 Workspace = 可持续修改的资源

Workspace 不属于某个 task。

它属于 run/thread：

```text
Run
└── Workspace
    ├── app artifact
    ├── current revision
    ├── preview
    └── verification
```

Task 只是对它做修改。

---

# 14. Resource Gate 真正替代 Phase Gate

## 14.1 当前问题

当前代码先做 resource prerequisite，随后仍：

```python
if call.name not in (
    ALLOWED_TOOLS[
        self.phase
    ]
):
    BLOCK
```

所以 Resource Gate 并没有成为权威。

尤其：

```python
RunPhase.DONE: set()
```

意味着已有 workspace 的 completed run 不能继续调用 workspace tools。

## 14.2 最终原则

权限判断：

```text
1. Tool 是否存在
2. Required resources 是否存在
3. Risk policy 是否允许
4. User approval 是否需要

与 RunPhase 无关
```

Phase 只表示：

```text
当前 Task UI 展示：
understanding
planning
generating
editing
verifying
previewing
```

## 14.3 删除 Phase 权限判断

从：

```python
workspace_state = (
    load_workspace_state(
        self.storage,
        run_id,
    )
)

allowed, missing = (
    check_tool_prerequisites(
        call.name,
        workspace_state,
    )
)

if (
    call.name
    in ALLOWED_TOOLS.get(
        self.phase,
        set(),
    )
    and not allowed
):
    ...

if (
    call.name
    not in ALLOWED_TOOLS.get(
        self.phase,
        set(),
    )
):
    ...
```

改成：

```python
workspace_state = (
    load_workspace_state(
        self.storage,
        run_id,
    )
)

allowed, missing = (
    check_tool_prerequisites(
        call.name,
        workspace_state,
    )
)

if not allowed:
    return ToolResult(
        tool=call.name,
        status=ToolStatus.BLOCKED,
        code=(
            "resource_prerequisite"
        ),
        error=(
            "Missing required resources: "
            + ", ".join(missing)
        ),
        data={
            "missing": missing,
            "available": sorted(
                available_resources(
                    workspace_state
                )
            ),
        },
        retryable=True,
    ).model_dump_json()
```

然后 phase gate 整体删除。

## 14.4 `plan_product` resource 条件更准确

当前 ToolSpec：

```text
plan_product requires capability_card
```

但 multi-paper composition 也可以作为输入。

Resource model 应支持 OR prerequisite。

例如：

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str

    requires_all:
        frozenset[str] = field(
            default_factory=frozenset
        )

    requires_any:
        tuple[
            frozenset[str],
            ...
        ] = ()

    produces:
        frozenset[str] = field(
            default_factory=frozenset
        )

    risk: ToolRisk = "read"
```

定义：

```python
"plan_product": ToolSpec(
    name="plan_product",

    requires_any=(
        frozenset({
            "capability_card"
        }),
        frozenset({
            "composition"
        }),
    ),

    produces=frozenset({
        "prd"
    }),
)
```

检查：

```python
def check_tool_prerequisites(
    tool_name: str,
    state: WorkspaceState,
) -> tuple[
    bool,
    list[str],
]:
    spec = TOOL_SPECS.get(
        tool_name
    )

    if not spec:
        return True, []

    available = (
        available_resources(
            state
        )
    )

    missing_all = (
        spec.requires_all
        - available
    )

    if missing_all:
        return (
            False,
            sorted(missing_all),
        )

    if spec.requires_any:
        if not any(
            group <= available
            for group
            in spec.requires_any
        ):
            description = [
                " OR ".join(
                    sorted(group)
                )
                for group
                in spec.requires_any
            ]

            return (
                False,
                [
                    "one of: "
                    + " | ".join(
                        description
                    )
                ],
            )

    return True, []
```

## 14.5 删除 `DONE → INIT`

当前 Messages API：

```python
if (
    run["status"] in {
        "done",
        "cancelled",
        "error",
    }
    or run.get("phase")
       == "done"
):
    update_run_phase(
        "init"
    )
```

应删除。

新 task 只创建：

```python
task = storage.create_task(
    run_id=run_id,
    goal=req.content,
    status="queued",
    phase="queued",
)
```

Run 本身继续保留已有 workspace。

---

# 15. Queue / Interrupt / Follow-up 的完整实现

## 15.1 API Contract

```python
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)


class MessageCreate(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=20_000,
    )

    paper_ids: list[str] = Field(
        default_factory=list
    )

    public_id: str | None = None

    mode: Literal[
        "start",
        "queue",
        "interrupt",
    ] = "start"
```

## 15.2 Queue 语义

```text
start:
没有活动任务才执行

queue:
无论是否有活动任务，创建 queued task；
当前 task 完成后开始

interrupt:
取消当前 active task；
保留已有 workspace；
当前输入作为高优先级下一 task
```

## 15.3 不要只用内存 Queue 作为唯一状态

数据库 Task 是 source of truth：

```text
queued
running
completed
```

RunQueue 只是 executor。

MVP：

```python
class RunTaskScheduler:
    def __init__(
        self,
        storage: Storage,
        task_manager:
            RunTaskManager,
    ) -> None:
        self.storage = storage
        self.task_manager = (
            task_manager
        )

        self._wakeups:
            dict[
                str,
                asyncio.Event,
            ] = defaultdict(
                asyncio.Event
            )

        self._workers:
            dict[
                str,
                asyncio.Task,
            ] = {}

    async def enqueue(
        self,
        run_id: str,
    ) -> None:
        event = self._wakeups[
            run_id
        ]

        event.set()

        worker = self._workers.get(
            run_id
        )

        if (
            worker is None
            or worker.done()
        ):
            self._workers[
                run_id
            ] = asyncio.create_task(
                self._worker(
                    run_id
                )
            )

    async def _worker(
        self,
        run_id: str,
    ) -> None:
        wake = self._wakeups[
            run_id
        ]

        while True:
            task = (
                self.storage
                .get_next_queued_task(
                    run_id
                )
            )

            if task is None:
                wake.clear()

                try:
                    await asyncio.wait_for(
                        wake.wait(),
                        timeout=1.0,
                    )
                except (
                    asyncio.TimeoutError
                ):
                    break

                continue

            orchestrator = (
                Orchestrator()
            )

            await orchestrator.run(
                run_id=run_id,
                user_message=(
                    task["goal"]
                ),
                task_id=task["id"],
            )
```

正式 production 版本再切 durable claim/lease。

## 15.4 Endpoint

```python
@router.post(
    "/{run_id}/messages"
)
async def send_message(
    run_id: str,
    req: MessageCreate,
    request: Request,
) -> dict:
    storage = get_storage()

    run = storage.get_run(
        run_id
    )

    if not run:
        raise HTTPException(
            404,
            "Run not found",
        )

    manager = (
        get_run_task_manager()
    )

    running = (
        manager.is_running(
            run_id
        )
    )

    if (
        req.mode == "start"
        and running
    ):
        raise HTTPException(
            409,
            (
                "Run is busy. "
                "Use queue or interrupt."
            ),
        )

    if (
        req.mode == "interrupt"
        and running
    ):
        await manager.cancel_and_wait(
            run_id
        )

    message = (
        storage.add_message(
            run_id=run_id,
            role="user",
            content=req.content,
            public_id=req.public_id,
        )
    )

    for paper_id in (
        req.paper_ids
    ):
        storage.attach_paper_to_run(
            run_id,
            paper_id,
        )

    task = storage.create_task(
        run_id=run_id,
        user_message_id=(
            message["id"]
        ),
        title=req.content[:120],
        goal=req.content,
        status="queued",
        phase="queued",
        priority=(
            100
            if req.mode
               == "interrupt"
            else 0
        ),
    )

    await scheduler.enqueue(
        run_id
    )

    return {
        "status": "queued",
        "run_id": run_id,
        "task_id": task["id"],
        "message": message,
    }
```

## 15.5 Interrupt 是否清理 queued tasks

建议不要默认清理所有 queued follow-ups。

可定义：

```text
interrupt current
= 只取消 active task

interrupt current + replace queue
= 未来可加显式 mode
```

默认保留用户已排队的信息，避免静默丢请求。

---

# 16. Task / Step 可观察执行模型

当前 Event 里有 `task_id`，但缺少真正统一的 Step domain。

建议新增表：

```sql
CREATE TABLE IF NOT EXISTS task_steps (
    id TEXT PRIMARY KEY,

    task_id TEXT NOT NULL
      REFERENCES tasks(id)
      ON DELETE CASCADE,

    kind TEXT NOT NULL,
    title TEXT NOT NULL,

    status TEXT NOT NULL
      DEFAULT 'pending',

    detail TEXT,
    summary TEXT,

    progress REAL,

    metadata TEXT,

    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    created_at TIMESTAMP NOT NULL
      DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS
idx_task_steps_task_id
ON task_steps(task_id, created_at);
```

## 16.1 ProgressReporter

```python
class ProgressReporter:
    def __init__(
        self,
        *,
        run_id: str,
        task_id: str,
        storage: Storage,
        emit: EventEmitter,
    ) -> None:
        self.run_id = run_id
        self.task_id = task_id
        self.storage = storage
        self.emit = emit

    async def start(
        self,
        *,
        kind: str,
        title: str,
        metadata:
            dict | None = None,
    ) -> str:
        step = (
            self.storage
            .create_task_step(
                task_id=(
                    self.task_id
                ),
                kind=kind,
                title=title,
                status="running",
                metadata=metadata,
            )
        )

        await self.emit.emit(
            "step.started",
            {
                "step_id": (
                    step["id"]
                ),
                "kind": kind,
                "title": title,
                "metadata": (
                    metadata or {}
                ),
            },
        )

        return step["id"]

    async def update(
        self,
        step_id: str,
        *,
        detail: str | None = None,
        progress:
            float | None = None,
    ) -> None:
        self.storage.update_task_step(
            step_id,
            detail=detail,
            progress=progress,
        )

        await self.emit.emit(
            "step.progress",
            {
                "step_id": step_id,
                "detail": detail,
                "progress": progress,
            },
        )

    async def complete(
        self,
        step_id: str,
        *,
        summary:
            str | None = None,
        metadata:
            dict | None = None,
    ) -> None:
        self.storage.complete_task_step(
            step_id,
            summary=summary,
        )

        await self.emit.emit(
            "step.completed",
            {
                "step_id": step_id,
                "summary": summary,
                "metadata": (
                    metadata or {}
                ),
            },
        )

    async def fail(
        self,
        step_id: str,
        error: str,
    ) -> None:
        self.storage.fail_task_step(
            step_id,
            error=error,
        )

        await self.emit.emit(
            "step.failed",
            {
                "step_id": step_id,
                "error": error,
            },
        )
```

## 16.2 Tool handler 统一包装

```python
async def with_step(
    ctx: ToolContext,
    *,
    kind: str,
    title: str,
    fn,
):
    if not ctx.task_id:
        return await fn(None)

    reporter = (
        ProgressReporter(
            run_id=ctx.run_id,
            task_id=ctx.task_id,
            storage=ctx.storage,
            emit=ctx.emit,
        )
    )

    step_id = await reporter.start(
        kind=kind,
        title=title,
    )

    try:
        result = await fn(
            reporter
        )

    except Exception as exc:
        await reporter.fail(
            step_id,
            str(exc),
        )

        raise

    await reporter.complete(
        step_id,
        summary=(
            result.summary
            if isinstance(
                result,
                ToolResult,
            )
            else None
        ),
    )

    return result
```

例如：

```python
async def handle_generate(
    args,
    ctx,
):
    async def run(
        progress,
    ):
        return await _generate_impl(
            args,
            ctx,
            progress,
        )

    return await with_step(
        ctx,
        kind="codegen",
        title=(
            "Generating application"
        ),
        fn=run,
    )
```

这会把目前零散的：

```text
run phase
tool.call
tool.result
```

升级为用户真正看得懂的 Agent activity。

---

# 17. Approval Policy V2

当前 `DANGEROUS_TOOLS` 是硬编码集合。

问题：

```text
apply_workspace_patch
```

每次都要求 HITL，会让真正的 continuous Agent 十分打断。

更合理是 risk based。

```python
class ApprovalMode(
    str,
    Enum,
):
    ALWAYS = "always"
    TRUST_WORKSPACE = (
        "trust_workspace"
    )
    MANUAL = "manual"


@dataclass
class ApprovalPolicy:
    mode: ApprovalMode

    workspace_isolated: bool
    network_enabled: bool

    def requires(
        self,
        spec: ToolSpec,
    ) -> bool:
        if (
            self.mode
            == ApprovalMode.ALWAYS
        ):
            return (
                spec.risk != "read"
            )

        if (
            self.mode
            == ApprovalMode.MANUAL
        ):
            return False

        # Trust writes/execs inside
        # isolated local workspace.
        if spec.risk in {
            "read",
            "workspace_write",
        }:
            return False

        if (
            spec.risk
            == "sandbox_exec"
            and self.workspace_isolated
        ):
            return False

        if spec.risk in {
            "network",
            "destructive",
        }:
            return True

        return True
```

UI 可以提供：

```text
Allow once
Always allow workspace edits for this run
Deny
```

而不是所有内部 file patch 都弹一次。

---

# 18. 第四阶段：Generation V3

当前 Generation V2 已经做对：

```text
multi-file
SafeWorkspacePolicy
WorkspacePlan schema
template scaffold
safe package scripts
atomic temp dir swap
```

但当前核心仍是：

```text
一次 LLM call
→ plan + 所有 files
→ 一个巨大 JSON
```

因此复杂 app 会遇到：

```text
context 大
JSON 容易损坏
一个文件错导致整个 output retry
难以 dependency-aware
无法分阶段 progress
难以 targeted regeneration
```

Generation V3 应改成：

```text
PRD
↓
Workspace Planner call
↓
WorkspacePlan
↓
Scaffold
↓
Types/Data batch
↓
Shared Components batch
↓
Routes batch
↓
Integration batch
↓
Typecheck
↓
Targeted Repair
↓
Build
```

---

# 19. WorkspacePlan 真正驱动分批生成

## 19.1 第一次只生成 plan

```python
async def plan_workspace(
    prd: dict,
    llm: LLMClient,
) -> WorkspacePlan:
    prompt = load_prompt(
        "workspace_planner"
    )

    response = await llm.chat(
        model=(
            get_config()
            .GENERATOR_MODEL
        ),
        messages=[
            Message(
                role="system",
                content=prompt,
            ),
            Message(
                role="user",
                content=json.dumps(
                    prd,
                    ensure_ascii=False,
                    indent=2,
                ),
            ),
        ],
        response_format={
            "type": "json_object"
        },
    )

    data = json.loads(
        response.content
        or "{}"
    )

    return (
        WorkspacePlan
        .model_validate(
            data
        )
    )
```

## 19.2 按 kind 分组

```python
GENERATION_ORDER = [
    "type",
    "fixture",
    "adapter",
    "hook",
    "component",
    "route",
    "api",
]


def group_plan_files(
    plan: WorkspacePlan,
) -> list[
    tuple[
        str,
        list[FileSpec],
    ]
]:
    by_kind: dict[
        str,
        list[FileSpec],
    ] = defaultdict(list)

    for file in plan.files:
        by_kind[
            file.kind
        ].append(file)

    return [
        (
            kind,
            by_kind[kind],
        )
        for kind
        in GENERATION_ORDER
        if by_kind.get(kind)
    ]
```

## 19.3 每 batch 一个 bounded LLM call

```python
class GeneratedFile(
    BaseModel
):
    path: str
    content: str


class GeneratedBatch(
    BaseModel
):
    summary: str
    files: list[GeneratedFile]


async def generate_batch(
    *,
    prd: dict,
    plan: WorkspacePlan,
    specs: list[FileSpec],
    workspace: Workspace,
    llm: LLMClient,
) -> GeneratedBatch:
    context = (
        build_generation_context(
            specs=specs,
            workspace=workspace,
        )
    )

    response = await llm.chat(
        model=(
            get_config()
            .GENERATOR_MODEL
        ),
        messages=[
            Message(
                role="system",
                content=load_prompt(
                    "workspace_batch_generator"
                ),
            ),
            Message(
                role="user",
                content=json.dumps(
                    {
                        "prd": prd,
                        "plan": (
                            plan.model_dump()
                        ),
                        "files_to_generate": [
                            spec.model_dump()
                            for spec
                            in specs
                        ],
                        "context": context,
                    },
                    ensure_ascii=False,
                ),
            ),
        ],
        response_format={
            "type": "json_object"
        },
    )

    return GeneratedBatch.model_validate(
        json.loads(
            response.content
            or "{}"
        )
    )
```

## 19.4 每 batch 后立即验证

```python
for kind, specs in (
    group_plan_files(plan)
):
    step_id = (
        await progress.start(
            kind="codegen",
            title=(
                f"Generating {kind}s"
            ),
        )
    )

    batch = await generate_batch(
        prd=prd,
        plan=plan,
        specs=specs,
        workspace=workspace,
        llm=llm,
    )

    changed = (
        workspace.apply_generated_batch(
            batch
        )
    )

    revision = (
        workspace.create_revision(
            source=(
                f"generate:{kind}"
            ),
            changed_files=changed,
        )
    )

    await progress.complete(
        step_id,
        summary=(
            f"{len(changed)} "
            "files generated"
        ),
        metadata={
            "revision_id": (
                revision.id
            ),
        },
    )
```

好处：

```text
某一批失败
≠
整个 App 重生

一个 route 出错
→
只重做 route batch
```

---

# 20. Context Selection / Dependency Graph

## 20.1 不要每次把整个 workspace 塞给模型

建立简单 import graph。

```python
IMPORT_RE = re.compile(
    r"""from\s+['"]([^'"]+)['"]"""
)


def parse_local_imports(
    source: str,
) -> set[str]:
    return {
        match.group(1)
        for match
        in IMPORT_RE.finditer(
            source
        )
        if match.group(1).startswith(
            "@/"
        )
    }
```

映射：

```python
def import_to_path(
    module: str,
) -> list[str]:
    if not module.startswith(
        "@/"
    ):
        return []

    base = module[2:]

    return [
        f"{base}.ts",
        f"{base}.tsx",
        f"{base}/index.ts",
        f"{base}/index.tsx",
    ]
```

## 20.2 Generation context

```python
def build_generation_context(
    *,
    specs: list[FileSpec],
    workspace: Workspace,
    max_chars: int = 80_000,
) -> list[dict]:
    required: list[str] = []

    for spec in specs:
        required.extend(
            spec.depends_on
        )

    # 再补共用 contract。
    required.extend([
        "types/",
        "lib/",
    ])

    selected = (
        workspace.select_files(
            required
        )
    )

    result = []
    used = 0

    for path in selected:
        content = (
            workspace.read(path)
        )

        remaining = (
            max_chars - used
        )

        if remaining <= 0:
            break

        clipped = (
            content[:remaining]
        )

        result.append({
            "path": path,
            "content": clipped,
        })

        used += len(clipped)

    return result
```

---

# 21. Safe Workspace Patch + Revision

Generation 和 Repair 都必须走同一个 patch engine。

不要：

```text
Generator 用 SafeWorkspacePolicy
Repair 直接 target.write_text()
```

应该：

```text
WorkspacePatch
      ↓
SafeWorkspacePolicy
      ↓
Revision transaction
```

## 21.1 Transaction helper

```python
@asynccontextmanager
async def workspace_transaction(
    workspace: Workspace,
    *,
    source: str,
):
    before = (
        workspace.create_revision(
            source=(
                source + ":before"
            )
        )
    )

    try:
        yield

    except Exception:
        workspace.restore_revision(
            before.id
        )
        raise

    else:
        after = (
            workspace.create_revision(
                source=(
                    source + ":after"
                )
            )
        )

        return after
```

Python async contextmanager 无法直接通过 `return` 暴露 after，正式实现可以用 result holder：

```python
@dataclass
class RevisionTransaction:
    before_id:
        str | None = None
    after_id:
        str | None = None
```

---

# 22. Targeted Repair V2

当前 verifier 的 repair context 会把所有 writable source file 都加入 prompt。

复杂 app 后会非常浪费。

目标：

```text
errors
↓
extract file paths
↓
add local dependencies
↓
add owning route/component
↓
max 8–12 files
```

## 22.1 Error path extraction

```python
TS_ERROR_RE = re.compile(
    r"(?P<path>"
    r"(?:app|components|hooks|lib|types)"
    r"/[^:(\s]+"
    r")"
    r"(?:\(|:)"
    r"(?P<line>\d+)"
)


def extract_error_paths(
    errors: list[str],
) -> list[str]:
    result: list[str] = []

    for error in errors:
        for match in (
            TS_ERROR_RE.finditer(
                error
            )
        ):
            path = match.group(
                "path"
            )

            if path not in result:
                result.append(path)

    return result
```

## 22.2 Expand local dependencies

```python
def expand_repair_context(
    workspace: Workspace,
    seed_paths: list[str],
    *,
    max_files: int = 12,
) -> list[str]:
    selected = list(
        seed_paths
    )

    cursor = 0

    while (
        cursor < len(selected)
        and len(selected)
            < max_files
    ):
        path = selected[
            cursor
        ]

        cursor += 1

        if not workspace.exists(
            path
        ):
            continue

        source = (
            workspace.read(path)
        )

        for module in (
            parse_local_imports(
                source
            )
        ):
            for candidate in (
                import_to_path(
                    module
                )
            ):
                if (
                    workspace.exists(
                        candidate
                    )
                    and candidate
                        not in selected
                ):
                    selected.append(
                        candidate
                    )

                    break

                if (
                    len(selected)
                    >= max_files
                ):
                    break

    return selected[
        :max_files
    ]
```

## 22.3 Repair output 必须是 WorkspacePatch

```python
async def propose_repair(
    *,
    errors: list[str],
    files: list[dict],
    llm: LLMClient,
) -> WorkspacePatch:
    response = await llm.chat(
        model=(
            get_config()
            .GENERATOR_MODEL
        ),
        messages=[
            Message(
                role="system",
                content=load_prompt(
                    "workspace_repair"
                ),
            ),
            Message(
                role="user",
                content=json.dumps(
                    {
                        "errors": errors,
                        "files": files,
                    },
                    ensure_ascii=False,
                ),
            ),
        ],
        response_format={
            "type": "json_object"
        },
    )

    return (
        WorkspacePatch
        .model_validate_json(
            response.content
            or "{}"
        )
    )
```

然后统一通过：

```python
apply_patch(
    workspace.path,
    patch,
    policy,
)
```

这样 repair 不会绕过 size/path policy。

---


# 23. 第五阶段：Verification V3

当前 verifier 已经有：

```text
Workspace
Static
Build
Runtime
Acceptance
```

这样的 layer，这是正确方向。

但最终仍然用：

```python
ready_for_preview = (
    build_succeeded
    and score >= 0.6
)
```

这会把“质量分数”和“硬错误”混在一起。

---

# 24. Hard Gates 与 Readiness 分层

## 24.1 定义

```python
class VerificationGates(
    BaseModel
):
    workspace_ok: bool
    typecheck_ok: bool
    lint_ok: bool
    build_ok: bool
    security_ok: bool

    runtime_ok:
        bool | None = None

    acceptance_ok:
        bool | None = None

    @property
    def technical_ready(
        self,
    ) -> bool:
        return all([
            self.workspace_ok,
            self.typecheck_ok,
            self.build_ok,
            self.security_ok,
        ])

    @property
    def preview_allowed(
        self,
    ) -> bool:
        # Preview 可以用于 debug，
        # 因此不要求 acceptance 已通过。
        return (
            self.workspace_ok
            and self.build_ok
        )

    @property
    def product_ready(
        self,
    ) -> bool:
        return (
            self.technical_ready
            and self.runtime_ok is True
            and self.acceptance_ok
                is True
        )
```

Lint 是否 hard gate 可以根据项目策略决定。建议：

```text
TypeScript error = hard
Build fail       = hard
Security critical = hard
Lint style warning = soft
```

## 24.2 Report

```python
report = {
    "app_id": app_id,
    "prd_id": prd_id,

    "gates": (
        gates.model_dump()
    ),

    "technical_ready": (
        gates.technical_ready
    ),

    "preview_allowed": (
        gates.preview_allowed
    ),

    "product_ready": (
        gates.product_ready
    ),

    "quality_score": (
        quality_score
    ),

    "layers": layers,

    "type_errors": (
        type_errors
    ),

    "lint_errors": (
        lint_errors
    ),

    "security_issues": (
        security_issues
    ),

    "browser_smoke": (
        browser_smoke
    ),
}
```

## 24.3 UI

不要只显示：

```text
Verified ✓
```

显示：

```text
Build          Passed
Typecheck      Passed
Runtime        Ready
Acceptance     4 / 5 passed
Security       Passed

Product ready  No
```

这样失败是可解释的。

---

# 25. Browser Acceptance Executor V2

建议 Browser Smoke 从一个大函数拆成 criterion executor。

```python
class AcceptanceExecutor:
    def __init__(
        self,
        *,
        page,
        context,
        base_url: str,
        timeout_ms: int,
    ) -> None:
        self.page = page
        self.context = context
        self.base_url = (
            base_url.rstrip("/")
        )
        self.timeout_ms = (
            timeout_ms
        )

    async def execute(
        self,
        criterion:
            AcceptanceCriterion,
    ) -> dict:
        if (
            criterion.test_kind
            == "api"
        ):
            return (
                await self._api(
                    criterion
                )
            )

        await self._goto(
            criterion.route
        )

        if (
            criterion.test_kind
            == "route"
        ):
            return {
                "status": "passed",
                "route": (
                    criterion.route
                ),
            }

        if (
            criterion.test_kind
            == "text"
        ):
            return (
                await self._text(
                    criterion
                )
            )

        if (
            criterion.test_kind
            == "interaction"
        ):
            return (
                await self._interaction(
                    criterion
                )
            )

        if (
            criterion.test_kind
            == "visual"
        ):
            return (
                await self._visual(
                    criterion
                )
            )

        raise RuntimeError(
            "Unsupported criterion kind"
        )
```

## 25.1 API

```python
async def _api(
    self,
    criterion:
        AcceptanceCriterion,
) -> dict:
    target = urljoin(
        self.base_url + "/",
        criterion.route.lstrip(
            "/"
        ),
    )

    response = (
        await self.context.request.get(
            target,
            timeout=self.timeout_ms,
        )
    )

    if (
        response.status
        >= 400
    ):
        raise RuntimeError(
            f"HTTP "
            f"{response.status} "
            f"for {target}"
        )

    if isinstance(
        criterion.expected,
        str,
    ):
        text = (
            await response.text()
        )

        if (
            criterion.expected
            not in text
        ):
            raise RuntimeError(
                "Expected API text "
                "not found."
            )

    return {
        "status": "passed",
        "status_code": (
            response.status
        ),
    }
```

## 25.2 Interaction

```python
async def _interaction(
    self,
    criterion:
        AcceptanceCriterion,
) -> dict:
    if not criterion.selector:
        raise RuntimeError(
            "Interaction criterion "
            "requires selector."
        )

    locator = (
        self.page
        .locator(
            criterion.selector
        )
        .first
    )

    await locator.wait_for(
        state="visible",
        timeout=self.timeout_ms,
    )

    match (
        criterion.action
    ):
        case "none":
            pass

        case "click":
            await locator.click(
                timeout=(
                    self.timeout_ms
                )
            )

        case "fill":
            if (
                criterion.input_value
                is None
            ):
                raise RuntimeError(
                    "fill requires "
                    "input_value"
                )

            await locator.fill(
                criterion.input_value
            )

        case "select":
            if (
                criterion.input_value
                is None
            ):
                raise RuntimeError(
                    "select requires "
                    "input_value"
                )

            await locator.select_option(
                criterion.input_value
            )

        case "upload":
            path = (
                resolve_test_fixture(
                    criterion
                    .input_value
                )
            )

            await (
                locator
                .set_input_files(
                    str(path)
                )
            )

        case _:
            raise RuntimeError(
                "Unsupported action"
            )

    await verify_expected(
        self.page,
        locator,
        criterion.expected,
    )

    return {
        "status": "passed",
        "action": (
            criterion.action
        ),
        "selector": (
            criterion.selector
        ),
    }
```

## 25.3 Browser noise 分类

当前任何 console error / requestfailed 都可能让 smoke 看起来失败。

建议分级：

```python
IGNORED_REQUEST_PATTERNS = [
    re.compile(
        r"/favicon\.ico$"
    ),
    re.compile(
        r"/_next/webpack-hmr"
    ),
]


def classify_request_failure(
    url: str,
    error: str,
) -> Literal[
    "ignore",
    "warning",
    "error",
]:
    if any(
        pattern.search(url)
        for pattern
        in IGNORED_REQUEST_PATTERNS
    ):
        return "ignore"

    if "ERR_ABORTED" in error:
        return "warning"

    return "error"
```

不要让开发服务器噪音污染产品验收。

---

# 26. Streaming Build / Test Runner

当前 verifier 已经存在 streaming helper 的方向，但主验证流程仍主要走 `_exec()`。

建议把 shell runner 统一为一个可靠的 process stream。

```python
@dataclass
class CommandResult:
    returncode: int

    stdout: str
    stderr: str

    timed_out: bool = False


async def run_command_stream(
    command: list[str],
    cwd: Path,
    *,
    timeout_s: float,
    on_line=None,
) -> CommandResult:
    process = await (
        asyncio
        .create_subprocess_exec(
            *command,
            cwd=str(cwd),
            stdout=(
                asyncio
                .subprocess
                .PIPE
            ),
            stderr=(
                asyncio
                .subprocess
                .STDOUT
            ),
        )
    )

    assert (
        process.stdout
        is not None
    )

    lines: list[str] = []

    async def consume() -> None:
        async for raw in (
            process.stdout
        ):
            text = raw.decode(
                errors="replace"
            )

            lines.append(text)

            if on_line:
                await on_line(
                    text.rstrip()
                )

    consumer = (
        asyncio.create_task(
            consume()
        )
    )

    timed_out = False

    try:
        await asyncio.wait_for(
            process.wait(),
            timeout=timeout_s,
        )

    except asyncio.TimeoutError:
        timed_out = True

        process.kill()

        await process.wait()

    finally:
        await consumer

    output = "".join(
        lines
    )

    return CommandResult(
        returncode=(
            process.returncode
            if process.returncode
                is not None
            else -1
        ),
        stdout=output,
        stderr="",
        timed_out=timed_out,
    )
```

注意这里 timeout 包的是：

```text
整个 process.wait()
```

而不是“每条 log callback”，否则一个完全不输出日志的挂死进程无法超时。

## 26.1 Progress integration

```python
step = await progress.start(
    kind="typecheck",
    title=(
        "Checking TypeScript"
    ),
)


async def on_line(
    line: str,
) -> None:
    await progress.update(
        step,
        detail=line[-500:],
    )


result = await run_command_stream(
    [
        "npm",
        "run",
        "typecheck",
        "--silent",
    ],
    app_path,
    timeout_s=120,
    on_line=on_line,
)

if (
    result.returncode == 0
    and not result.timed_out
):
    await progress.complete(
        step,
        summary=(
            "TypeScript passed"
        ),
    )
else:
    await progress.fail(
        step,
        "TypeScript failed",
    )
```

---

# 27. 第六阶段：Conversation / Turn UI 重构

这是前端从“后台 Job UI”变成“现代 Agent UI”的核心。

当前 UI：

```text
messages
↓
pending approvals
↓
AgentActivity(last 20 events)
```

问题：

```text
Step / Tool / Approval
不属于具体用户 turn
```

用户连续三轮后，Agent Activity 只是一个全局日志。

目标：

```text
User Task A
  Assistant
    ✓ Read paper
    ✓ Planned app
    ✓ Generated 12 files
  Final response

User Task B
  Assistant
    ✓ Inspected workspace
    ✓ Edited Sidebar.tsx
    ✓ Typecheck passed
  Final response
```

---

# 28. Composer 重构

## 28.1 当前问题

当前：

```ts
if (
  !content
  || sending
  || isRunning
) return
```

并且 user optimistic message：

```ts
streaming: true
status: "streaming"
```

API 支持 `public_id` 参数，但调用没有传 optimistic ID。

## 28.2 统一 `submitMessage(mode)`

```typescript
type SendMode =
  | "start"
  | "queue"
  | "interrupt";


async function resolvePaperIds(
  attachments: Attachment[],
): Promise<string[]> {
  const ids: string[] = [];

  for (
    const attachment
    of attachments
  ) {
    if (
      attachment.type
        === "paper"
      && attachment.paperId
    ) {
      ids.push(
        attachment.paperId
      );

      continue;
    }

    if (!attachment.file) {
      continue;
    }

    if (
      attachment.file.type
      !== "application/pdf"
    ) {
      throw new Error(
        "PaperForge currently "
        "supports PDF attachments only"
      );
    }

    const uploaded =
      await api.uploadPaper(
        attachment.file
      );

    ids.push(
      uploaded.paper_id
    );
  }

  return ids;
}
```

```typescript
const submitMessage =
  async (
    mode: SendMode,
  ) => {
    const content =
      input.trim();

    if (
      !content
      || sending
      || submitLock.current
    ) {
      return;
    }

    submitLock.current = true;
    setSending(true);

    const publicId =
      crypto.randomUUID();

    const optimistic: Message = {
      id: publicId,
      public_id: publicId,
      role: "user",
      content,

      // 用户输入已经完整。
      streaming: false,
      status: "completed",
    };

    addMessage(
      optimistic
    );

    try {
      const paperIds =
        await resolvePaperIds(
          attachments
        );

      await api.sendMessage(
        currentRun.id,
        content,
        paperIds,
        publicId,
        mode,
      );

      setInput("");
      clearAttachments();

    } catch (error) {
      removeMessage(
        publicId
      );

      setInput(
        content
      );

      throw error;

    } finally {
      submitLock.current = false;
      setSending(false);
    }
  };
```

## 28.3 textarea 永远可输入

```tsx
<textarea
  value={input}
  disabled={sending}
  placeholder={
    isRunning
      ? "Add a follow-up..."
      : "Ask PaperForge..."
  }
/>
```

## 28.4 Send button

空闲：

```text
[↑]
```

运行中：

```text
[Queue ↑] [▼]
```

Dropdown：

```text
Send after current task
Interrupt current task and send
```

Stop：

```text
■
```

作为独立紧凑按钮。

## 28.5 删除永久 Quick Actions

当前五个：

```text
Productize
Alternatives
Revise PRD
Fix build
Restart preview
```

不要永久显示。

### Empty thread

显示：

```text
Productize a paper
Explore a paper
Compare papers
```

### 之后

用户输入 `/` 时 command palette：

```typescript
const COMMANDS = [
  {
    id: "productize",
    label: "Productize paper",
    prompt: (
      "Productize the attached "
      "paper end-to-end."
    ),
  },
  {
    id: "fix",
    label: "Fix current app",
    prompt: (
      "Inspect the current "
      "workspace, fix the latest "
      "failure, and verify it."
    ),
  },
  {
    id: "restart-preview",
    label: "Restart preview",
    prompt: (
      "Restart the current "
      "preview sandbox."
    ),
  },
];
```

---

# 29. Turn Projection 与 Inline Steps

## 29.1 最好让 message 带 `task_id`

数据库 migration：

```sql
ALTER TABLE messages
ADD COLUMN task_id TEXT
REFERENCES tasks(id)
ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS
idx_messages_task_id
ON messages(task_id, created_at);
```

API 保存 user message 后再创建 task 当前存在顺序问题。

建议：

```text
先生成 task_id
↓
保存 user message(task_id)
↓
创建 task(user_message_id)
```

可以先在应用层生成 task id。

```python
task_id = (
    f"task_{uuid.uuid4().hex}"
)

message = storage.add_message(
    run_id=run_id,
    role="user",
    content=req.content,
    public_id=req.public_id,
    task_id=task_id,
)

task = storage.create_task(
    id=task_id,
    run_id=run_id,
    user_message_id=(
        message["id"]
    ),
    goal=req.content,
    status="queued",
)
```

Assistant streaming message：

```python
self.storage.create_streaming_message(
    run_id,
    message_id,
    task_id=self.task_id,
)
```

Tool result message：

```python
storage.add_message(
    run_id=run_id,
    role="tool",
    content=result_str,
    tool_call_id=call.id,
    task_id=self.task_id,
)
```

这样所有 timeline 数据天然有 task 归属。

## 29.2 Frontend types

```typescript
interface ConversationTurn {
  id: string;

  task: Task;

  userMessage:
    Message | null;

  assistantMessages:
    Message[];

  steps:
    AgentStep[];

  approvals:
    Approval[];

  artifacts:
    Artifact[];

  status:
    Task["status"];
}
```

## 29.3 Projection

```typescript
export function projectTurns(
  tasks: Task[],
  messages: Message[],
  steps: AgentStep[],
  approvals: Approval[],
  artifacts: Artifact[],
): ConversationTurn[] {
  const messageByTask =
    groupByTask(
      messages
    );

  const stepByTask =
    groupByTask(
      steps
    );

  const approvalByTask =
    groupByTask(
      approvals
    );

  const artifactByTask =
    groupByTask(
      artifacts
    );

  return tasks.map(
    (task) => {
      const taskMessages =
        messageByTask[
          task.id
        ] ?? [];

      return {
        id: task.id,
        task,
        userMessage:
          taskMessages.find(
            (message) =>
              message.role
                === "user"
          ) ?? null,

        assistantMessages:
          taskMessages.filter(
            (message) =>
              message.role
                === "assistant"
          ),

        steps:
          stepByTask[
            task.id
          ] ?? [],

        approvals:
          approvalByTask[
            task.id
          ] ?? [],

        artifacts:
          artifactByTask[
            task.id
          ] ?? [],

        status:
          task.status,
      };
    }
  );
}
```

## 29.4 Turn UI

```tsx
function Turn({
  turn,
}: {
  turn: ConversationTurn;
}) {
  return (
    <section
      data-task-id={
        turn.id
      }
      className="
        space-y-4
        py-6
      "
    >
      {turn.userMessage && (
        <UserMessage
          message={
            turn.userMessage
          }
        />
      )}

      <div
        className="
          mx-auto
          w-full
          max-w-[800px]
        "
      >
        <AssistantIdentity />

        <StepGroup
          steps={turn.steps}
        />

        {turn.approvals.map(
          (approval) => (
            <ApprovalCard
              key={
                approval.id
              }
              approval={
                approval
              }
            />
          )
        )}

        {turn.assistantMessages.map(
          (message) => (
            <AssistantMessage
              key={
                message.public_id
                ?? message.id
              }
              message={
                message
              }
            />
          )
        )}
      </div>
    </section>
  );
}
```

这会比全局：

```text
AgentActivity events.slice(-20)
```

高级和可理解很多。

---

# 30. Markdown Streaming 与渲染性能

ReactMarkdown 对超长 streaming message 每帧重新 parse 仍可能很重。

可以分两级。

## 30.1 第一阶段：memo + rAF

通常已经够用。

## 30.2 第二阶段：streaming plain-ish renderer

Streaming 时：

```tsx
function AssistantMessage({
  message,
}: {
  message: Message;
}) {
  if (message.streaming) {
    return (
      <StreamingMarkdown
        content={
          message.content
        }
      />
    );
  }

  return (
    <MemoizedMarkdown
      content={
        message.content
      }
    />
  );
}
```

`StreamingMarkdown` 可以只做轻量 GFM subset，完成时再用完整 Markdown parser。

或者按 block memoization：

```typescript
function splitMarkdownBlocks(
  markdown: string,
) {
  return markdown.split(
    /\n{2,}/
  );
}
```

已稳定 block 不重新解析，仅最后一个 block 更新。

不建议做人工逐字符 typing animation。

---

# 31. 第七阶段：Workbench 深度重构

当前 desktop：

```text
Chat 42%
PreviewPanel 58%
```

无 Preview 时也存在整个 Workbench。

这正是当前截图“生硬”的核心来源之一。

目标：

```text
无 workspace：
Sidebar | centered Conversation

有文件变更：
Sidebar | Conversation | Workbench Peek

preview.ready：
Sidebar | Conversation | Workbench Open
```

---

# 32. Adaptive `closed / peek / open`

## 32.1 Store

```typescript
export type WorkbenchMode =
  | "closed"
  | "peek"
  | "open";

interface WorkbenchSlice {
  mode: WorkbenchMode;

  userPinnedClosed:
    boolean;

  activeTab:
    WorkbenchTab;

  setMode(
    mode: WorkbenchMode
  ): void;

  closeWorkbench(): void;
  openWorkbench(): void;
}
```

## 32.2 自动策略

```typescript
export function applyWorkbenchEvent(
  event: RunEvent,
) {
  const store =
    useAppStore.getState();

  if (
    store.userPinnedClosed
  ) {
    return;
  }

  switch (event.type) {
    case "file.changed":
    case "artifact.created":
      if (
        store.workbenchMode
        === "closed"
      ) {
        store.setWorkbenchMode(
          "peek"
        );
      }
      break;

    case "preview.ready":
      store.setWorkbenchMode(
        "open"
      );
      store.setActiveTab(
        "preview"
      );
      break;
  }
}
```

## 32.3 Desktop layout

不要继续给 closed/open 都使用固定 `PanelGroup`。

可以：

```tsx
<div
  className="
    flex h-full
    min-w-0
  "
>
  <Conversation
    className="
      min-w-0 flex-1
    "
  />

  {mode !== "closed" && (
    <>
      <ResizeHandle />

      <aside
        className={cn(
          "min-w-0",
          "transition-[width]",
          "duration-200",
          mode === "peek"
            ? "w-[360px]"
            : [
                "w-[min(",
                "56vw,",
                "1040px",
                ")]",
              ].join("")
        )}
      >
        <Workbench />
      </aside>
    </>
  )}
</div>
```

如果希望 resize 持久化：

```text
peek = 固定窄栏
open = resizable Panel
```

即可。

---

# 33. 拆分约 900 行 `PreviewPanel.tsx`

目标目录：

```text
web/components/workbench/

  Workbench.tsx
  WorkbenchTabs.tsx
  WorkbenchHeader.tsx

  preview/
    PreviewView.tsx
    PreviewFrame.tsx
    PreviewToolbar.tsx

  editor/
    EditorView.tsx
    FileTree.tsx
    EditorTabs.tsx
    CodeEditor.tsx

  changes/
    ChangesView.tsx
    RevisionList.tsx
    DiffViewer.tsx

  tests/
    TestsView.tsx
    VerificationSummary.tsx
    AcceptanceResults.tsx

  artifacts/
    ArtifactsView.tsx
    ArtifactRow.tsx

  logs/
    LogsView.tsx
    LogToolbar.tsx

  hooks/
    useWorkbench.ts
    usePreview.ts
    useWorkspaceFiles.ts
    useEditorTabs.ts
```

`Workbench.tsx` 只负责：

```tsx
export function Workbench() {
  const activeTab =
    useWorkbenchStore(
      (state) =>
        state.activeTab
    );

  return (
    <section
      className="
        flex h-full
        min-w-0
        flex-col
      "
    >
      <WorkbenchHeader />
      <WorkbenchTabs />

      <div
        className="
          min-h-0
          flex-1
        "
      >
        {activeTab
          === "preview"
          && <PreviewView />}

        {activeTab
          === "code"
          && <EditorView />}

        {activeTab
          === "changes"
          && <ChangesView />}

        {activeTab
          === "tests"
          && <TestsView />}

        {activeTab
          === "artifacts"
          && <ArtifactsView />}

        {activeTab
          === "logs"
          && <LogsView />}
      </div>
    </section>
  );
}
```

---

# 34. Changes / Tests / Logs / Artifacts 交互

## 34.1 Changes

不要只是文件列表。

展示：

```text
Revision
Agent edit · “Make sidebar narrower”
3 files changed

Sidebar.tsx      +18 -12
layout.tsx       +4  -2
globals.css      +6  -1
```

支持：

```text
View diff
Revert revision
Ask PaperForge to revise
```

## 34.2 Tests

Verification 显示按 layer：

```text
Technical
✓ Workspace
✓ TypeScript
✓ Build
✓ Security

Product
✓ Runtime
✗ Acceptance
  4 / 5 passed
```

失败 criterion：

```text
AC-5 Export button downloads result
Selector: [data-testid=export]
Action: click
Expected: Download started

[Ask PaperForge to fix]
```

点击按钮：

```ts
setComposerPrefill(
  "Fix the failing acceptance criterion AC-5. "
  + "Inspect the current workspace, make the minimal change, "
  + "then rerun the relevant checks."
);
```

## 34.3 Logs

日志默认只跟随 active Step。

Toolbar：

```text
[All] [Build] [Preview]
Follow logs ✓
Clear local view
```

不要把所有内部 debug event 混进 logs。

## 34.4 Artifacts

Artifact 应该按产品语言分类：

```text
Paper Understanding
Capability Card

Product
PRD

Application
Workspace

Verification
Latest Report
```

而不是把 artifact type 直接当开发者数据结构。

---

# 35. 第八阶段：前端 State / Type Contract 重构

当前 Zustand 一个 store 里混：

```text
run
messages
events
sandbox
tasks
preview
approvals
artifacts
attachments
isRunning
activeTab
lastSeq
composerPrefill
```

并有大量 `any`。

建议先拆 slice，不必立刻换库。

```text
web/lib/store/

  index.ts

  run-slice.ts
  conversation-slice.ts
  task-slice.ts
  workbench-slice.ts
  attachment-slice.ts
  ui-slice.ts
```

## 35.1 Debug Event ring buffer

当前 events 不应该无限增长：

```typescript
const MAX_DEBUG_EVENTS =
  500;

addDebugEvent:
  (event) =>
    set((state) => ({
      events: [
        ...state.events,
        event,
      ].slice(
        -MAX_DEBUG_EVENTS
      ),
    }));
```

## 35.2 OpenAPI Generated Types

FastAPI 已经有 OpenAPI。

```bash
npx openapi-typescript \
  http://localhost:8000/openapi.json \
  -o web/lib/api/schema.d.ts
```

```typescript
import type {
  components,
} from "@/lib/api/schema";

export type RunResponse =
  components["schemas"][
    "RunResponse"
  ];

export type MessageResponse =
  components["schemas"][
    "MessageResponse"
  ];
```

Event type 单独使用 discriminated union：

```typescript
interface RunEventBase<
  T extends string,
  P,
> {
  version: 2;

  id: string;
  seq: number;

  run_id: string;
  task_id:
    string | null;

  type: T;
  ts: number;

  payload: P;
}


type KnownRunEvent =
  | RunEventBase<
      "message.delta",
      {
        message_id: string;
        delta: string;
      }
    >
  | RunEventBase<
      "step.started",
      {
        step_id: string;
        kind: string;
        title: string;
      }
    >
  | RunEventBase<
      "file.changed",
      {
        path: string;
        revision_id: string;
      }
    >;
```

---

# 36. 第九阶段：Parser / Capability Contract

这不是当前最紧急问题，但产品做深以后很重要。

现在 Parser 应该从：

```text
CapabilityCard
```

逐步升级成：

```text
CapabilityContract
```

原因：产品化真正需要的不是“论文摘要”，而是：

```text
输入是什么
输出是什么
需要哪些模型
有什么 precondition
失败模式
推理成本
有没有开源实现
能不能 mock
如何 real integration
```

## 36.1 Schema

```python
class CapabilityInput(
    BaseModel
):
    name: str
    type: str

    required: bool = True
    description: str = ""


class CapabilityOutput(
    BaseModel
):
    name: str
    type: str
    description: str = ""


class ImplementationReference(
    BaseModel
):
    kind: Literal[
        "github",
        "project_page",
        "model",
        "dataset",
        "api",
        "paper",
    ]

    url: str
    label: str = ""


class CapabilityContract(
    BaseModel
):
    name: str
    description: str

    inputs:
        list[CapabilityInput]

    outputs:
        list[CapabilityOutput]

    preconditions:
        list[str]

    failure_modes:
        list[str]

    compute_requirements:
        list[str]

    integration_mode: Literal[
        "mock",
        "local_model",
        "remote_api",
        "unknown",
    ]

    implementation_refs:
        list[
            ImplementationReference
        ]

    confidence: float
```

## 36.2 长论文不要只截前 32 chunks

推荐 hierarchical summary tree：

```python
async def reduce_paper(
    chunks: list[PaperChunk],
    llm: LLMClient,
):
    level = [
        await summarize_chunk(
            chunk,
            llm,
        )
        for chunk
        in chunks
    ]

    while (
        len(level) > 6
    ):
        groups = batched(
            level,
            6,
        )

        level = [
            await summarize_group(
                group,
                llm,
            )
            for group
            in groups
        ]

    return await (
        synthesize_contract(
            level,
            llm,
        )
    )
```

`ParseCoverage` 继续保留：

```text
processed pages
omitted pages
complete
```

如果确实预算不足，前端应明确：

```text
Parsed 38 / 74 pages
Partial understanding
```

而不是无提示。

---

# 37. 第十阶段：Durable Worker / Event Broker / Production Runtime

这部分可以最后做，但正式部署前需要。

当前 Task persistence 和 live coroutine execution 是两层：

```text
SQLite tasks
+
进程内 asyncio Task
```

服务重启后需要：

```text
stale running
→ queued
→ worker 自动 claim
→ resume/retry
```

而不能只是状态改回 queued。

## 37.1 Worker Lease

```sql
ALTER TABLE tasks
ADD COLUMN lease_owner TEXT;

ALTER TABLE tasks
ADD COLUMN lease_until TIMESTAMP;

ALTER TABLE tasks
ADD COLUMN attempt INTEGER
NOT NULL DEFAULT 0;
```

Claim：

```python
def claim_next_task(
    storage: Storage,
    worker_id: str,
) -> dict | None:
    lease_until = (
        utcnow()
        + timedelta(
            minutes=5
        )
    )

    with (
        storage.transaction()
        as conn
    ):
        task = conn.execute(
            """
            SELECT *
            FROM tasks
            WHERE status = 'queued'
            ORDER BY
              priority DESC,
              created_at ASC
            LIMIT 1
            """
        ).fetchone()

        if not task:
            return None

        conn.execute(
            """
            UPDATE tasks
            SET
              status='running',
              lease_owner=?,
              lease_until=?,
              attempt=attempt+1
            WHERE id=?
            """,
            (
                worker_id,
                lease_until,
                task["id"],
            ),
        )

    return dict(task)
```

## 37.2 Heartbeat

```python
async def heartbeat(
    storage,
    task_id: str,
    worker_id: str,
):
    while True:
        await asyncio.sleep(30)

        storage.renew_task_lease(
            task_id=task_id,
            worker_id=worker_id,
            lease_until=(
                utcnow()
                + timedelta(
                    minutes=5
                )
            ),
        )
```

## 37.3 EventStore / EventBroker

当前 EventManager live fanout 是进程内 queue。

抽象：

```python
class EventStore(Protocol):
    def append(
        self,
        event: Event,
    ) -> Event:
        ...

    def list_after(
        self,
        run_id: str,
        seq: int,
    ) -> list[Event]:
        ...


class EventBroker(Protocol):
    async def publish(
        self,
        event: Event,
    ) -> None:
        ...

    async def subscribe(
        self,
        run_id: str,
    ):
        ...
```

Local：

```python
class InProcessBroker:
    ...
```

Production：

```text
Redis Pub/Sub
或
Postgres LISTEN/NOTIFY
```

PaperForge 当前阶段不用立刻上 Redis；先保证 interface，再在真正多 worker 时替换。

---

# 38. Preview / Sandbox 安全强化

正式部署时建议：

```text
main app:
app.paperforge.dev

preview:
<random>.preview.paperforge.dev
```

不要让用户生成 app 与主站同 origin。

## 38.1 Preview token

```python
def create_preview_token(
    sandbox_id: str,
    user_id: str,
    *,
    expires_in: int = 3600,
) -> str:
    return signer.sign({
        "sandbox_id":
            sandbox_id,
        "user_id":
            user_id,
        "exp":
            time.time()
            + expires_in,
    })
```

Preview URL：

```text
https://sb-xxx.preview.paperforge.dev/?token=...
```

## 38.2 Container hardening

根据生成 app 所需最小权限设置：

```text
read-only base image
workspace mount limited
no host docker socket
memory limit
CPU quota
pids limit
network default deny / allowlist
non-root user
seccomp
```

如果模型生成应用默认只有 mock adapter：

```text
network off
```

只有用户明确配置 real API integration 时再允许受控 network。

---

# 39. Observability / SLO

## 39.1 Streaming

Backend：

```text
provider_request_at
provider_first_delta_at
message_delta_emitted_at
event_persisted_at
sse_yielded_at
```

Frontend：

```text
sse_received_at
delta_flush_at
render_visible_at
```

指标：

```text
provider_ttft_ms
provider_to_sse_ms
sse_to_render_ms
first_visible_token_ms

message_raw_chunks
message_delta_events
message_checkpoints

sse_gap_total
rehydrate_total
```

目标：

```text
SSE receive → visible:
p95 < 50 ms

Provider first delta
→ visible:
额外开销 p95 < 150 ms

React streaming renders:
<= 30 / second / active message
```

## 39.2 Agent

```text
task_queue_wait_ms
task_duration_ms

step_duration_ms
tool_duration_ms

approval_wait_ms

generation_plan_ms
generation_batch_ms

repair_attempts

build_duration_ms

preview_ready_ms
```

## 39.3 Product quality

```text
must_acceptance_pass_rate

build_first_pass_rate

repair_success_rate

average_files_per_generation

generation_retry_rate

browser_smoke_flake_rate
```

这些指标能帮助判断：

```text
“Agent 是不是越来越好用”
```

而不是只看 UI。

---


# 40. 测试矩阵与核心测试代码

这一轮必须补“集成闭环测试”，因为当前最明显的问题恰好都是：

```text
A 文件已经改了
B 文件没同步
```

例如 `loop.py` 给 `ToolContext` 传 `task_id`，但 `tools.py` constructor 没接。

单文件 unit test 很难发现这种错误。

---

## 40.1 P0：Orchestrator 能真正启动

新增：

```text
tests/integration/test_orchestrator_context_contract.py
```

```python
@pytest.mark.asyncio
async def test_orchestrator_constructs_tool_context(
    storage,
    fake_llm,
):
    run = storage.create_run(
        title="Test"
    )

    task = storage.create_task(
        run_id=run["id"],
        title="Test",
        goal="hello",
        status="queued",
        phase="init",
    )

    storage.add_message(
        run_id=run["id"],
        role="user",
        content="hello",
    )

    orchestrator = Orchestrator(
        llm=fake_llm,
        storage=storage,
    )

    # 最重要的是不能在 ToolContext
    # construction 时 TypeError。
    await orchestrator.run(
        run_id=run["id"],
        user_message="hello",
        task_id=task["id"],
    )
```

fake LLM 可以直接返回无 tool text，避免测试依赖 provider。

---

## 40.2 Workspace artifact restore

```python
def test_nextjs_app_artifact_restores_workspace(
    storage,
    tmp_path,
):
    run = storage.create_run(
        title="Workspace"
    )

    app_path = (
        tmp_path / "app"
    )

    app_path.mkdir()

    artifact_id = (
        storage.save_artifact(
            run_id=run["id"],
            artifact_type=(
                "nextjs_app"
            ),
            data={
                "app_id":
                    "app_1"
            },
            metadata={
                "app_path":
                    str(app_path)
            },
        )
    )

    state = load_workspace_state(
        storage,
        run["id"],
    )

    assert (
        state.app_id
        == artifact_id
    )

    assert (
        state.workspace_path
        == str(app_path)
    )

    assert (
        "workspace"
        in available_resources(
            state
        )
    )
```

---

## 40.3 Workspace tool registration consistency

非常建议加 contract test，防止“Phase/ToolSpec 有名字但 dispatcher 没实现”再次发生。

```python
def test_workspace_tool_registry_is_consistent():
    declared = {
        definition.name
        for definition
        in TOOL_DEFINITIONS
    }

    gated = set(
        TOOL_SPECS.keys()
    )

    handlers = set(
        TOOL_HANDLERS.keys()
    )

    required = {
        "inspect_workspace",
        "read_workspace_file",
        "apply_workspace_patch",
        "run_checks",
    }

    assert required <= declared
    assert required <= gated
    assert required <= handlers
```

更进一步：

```python
def test_all_declared_tools_have_handlers():
    declared = {
        item.name
        for item
        in TOOL_DEFINITIONS
    }

    assert (
        declared
        <= set(
            TOOL_HANDLERS
        )
    )
```

---

## 40.4 Resource Gate 连续编辑测试

```python
@pytest.mark.asyncio
async def test_completed_generation_can_be_edited_without_reparse(
    storage,
    workspace_artifact,
):
    state = load_workspace_state(
        storage,
        workspace_artifact.run_id,
    )

    allowed, missing = (
        check_tool_prerequisites(
            "apply_workspace_patch",
            state,
        )
    )

    assert allowed
    assert missing == []
```

同时测试**没有 phase 依赖**：

```python
@pytest.mark.asyncio
async def test_workspace_edit_is_not_blocked_by_done_phase(
    orchestrator,
    workspace_context,
):
    orchestrator.phase = (
        RunPhase.DONE
    )

    result = await (
        orchestrator
        ._execute_tool_call(
            ToolCall(
                id="call_1",
                name=(
                    "inspect_workspace"
                ),
                args={},
            ),
            workspace_context,
            workspace_context.emit,
            workspace_context.run_id,
        )
    )

    parsed = json.loads(
        result
    )

    assert (
        parsed["status"]
        != "blocked"
    )
```

这个测试应该在删除 Phase Gate 后落地。

---

## 40.5 Anthropic tool streaming

最低 regression：

```python
@pytest.mark.asyncio
async def test_anthropic_stream_preserves_tool_calls(
    provider,
    monkeypatch,
):
    response = ChatResponse(
        content=(
            "I will inspect "
            "the workspace."
        ),
        tool_calls=[
            ToolCall(
                id="call_1",
                name=(
                    "inspect_workspace"
                ),
                args={},
            )
        ],
        finish_reason="tool_use",
    )

    async def fake_chat(
        *args,
        **kwargs,
    ):
        return response

    monkeypatch.setattr(
        provider,
        "chat",
        fake_chat,
    )

    chunks = [
        chunk
        async for chunk
        in provider.stream(
            model="test",
            messages=[],
            tools=[
                ToolDefinition(
                    name=(
                        "inspect_workspace"
                    ),
                    description="x",
                    input_schema={
                        "type": "object"
                    },
                )
            ],
        )
    ]

    calls = [
        call
        for chunk in chunks
        for call
        in (
            chunk.tool_calls
            or []
        )
    ]

    assert [
        call.name
        for call
        in calls
    ] == [
        "inspect_workspace"
    ]
```

---

## 40.6 Browser route criterion

```python
@pytest.mark.asyncio
async def test_route_criterion_uses_route_not_selector(
    fake_preview,
):
    prd = {
        "acceptance_criteria": [
            {
                "id": "ac_route",
                "feature_id": "f1",
                "priority": "must",
                "description": (
                    "Settings route "
                    "loads"
                ),
                "test_kind": "route",
                "route": "/settings",
                "selector": (
                    "[data-testid="
                    "'settings']"
                ),
                "action": "none",
                "expected": None,
            }
        ]
    }

    result = await (
        run_browser_smoke(
            base_url=(
                fake_preview.url
            ),
            prd=prd,
            output_dir=(
                fake_preview
                .output_dir
            ),
        )
    )

    assert (
        result["checks"][0]
        ["status"]
        == "passed"
    )

    assert (
        "/settings"
        in fake_preview
        .requested_urls
    )
```

---

## 40.7 Browser fill action

```python
@pytest.mark.asyncio
async def test_interaction_fill_uses_input_value(
    preview_with_form,
):
    prd = {
        "acceptance_criteria": [
            {
                "id": "ac_fill",
                "feature_id": "f1",
                "priority": "must",
                "description": (
                    "Search input works"
                ),
                "test_kind": (
                    "interaction"
                ),
                "route": "/",
                "selector": (
                    "[data-testid="
                    "'search']"
                ),
                "action": "fill",
                "input_value": "paper",
                "expected": "paper",
            }
        ]
    }

    result = await (
        run_browser_smoke(
            preview_with_form.url,
            prd,
            preview_with_form
                .output_dir,
        )
    )

    assert (
        result["checks"][0]
        ["status"]
        == "passed"
    )
```

---

## 40.8 SSE unknown event

```typescript
it(
  "ignores future events without hydration",
  () => {
    useAppStore.setState({
      lastSeq: 10,
    });

    const result =
      applyRunEvent(
        {
          version: 2,
          id: "evt_11",
          seq: 11,
          run_id: "run_1",
          task_id: "task_1",
          type: (
            "future.event"
          ),
          ts: Date.now(),
          payload: {},
        },
        "run_1",
      );

    expect(result).toBe(
      "ignored"
    );

    expect(
      useAppStore
        .getState()
        .lastSeq
    ).toBe(11);
  }
);
```

---

## 40.9 Real seq gap

```typescript
it(
  "rehydrates only on a real gap",
  () => {
    useAppStore.setState({
      lastSeq: 10,
    });

    const result =
      applyRunEvent(
        {
          version: 2,
          id: "evt_12",
          seq: 12,
          run_id: "run_1",
          task_id: "task_1",
          type: (
            "message.delta"
          ),
          ts: Date.now(),
          payload: {
            message_id:
              "msg_1",
            delta: "x",
          },
        },
        "run_1",
      );

    expect(result).toBe(
      "gap"
    );
  }
);
```

---

## 40.10 Playwright：真正验证“完成前就有流式文本”

不要只测 store。

```typescript
test(
  "assistant text is visible before task finishes",
  async ({ page }) => {
    await page.goto(
      "/runs/run_stream_test"
    );

    const composer =
      page.getByPlaceholder(
        /Ask PaperForge/
      );

    await composer.fill(
      "Explain the paper"
    );

    await page
      .getByRole(
        "button",
        { name: /send/i }
      )
      .click();

    const assistant =
      page.getByTestId(
        "assistant-message-current"
      );

    await expect(
      assistant
    ).not.toHaveText("");

    await expect(
      page.getByTestId(
        "task-status"
      )
    ).toHaveText(
      /running/i
    );
  }
);
```

这条测试最关键：

```text
文本必须在 task finished 之前出现
```

否则所谓 streaming 仍没有真正从用户视角成立。

---

## 40.11 Reload during stream

```typescript
test(
  "reload resumes a stream without duplicate content",
  async ({ page }) => {
    await startLongTask(
      page
    );

    const assistant =
      page.getByTestId(
        "assistant-message-current"
      );

    await expect(
      assistant
    ).toContainText(
      "partial"
    );

    const before =
      await assistant.textContent();

    await page.reload();

    await expect(
      page.getByTestId(
        "assistant-message-current"
      )
    ).toContainText(
      "partial"
    );

    await waitForTaskFinish(
      page
    );

    const after =
      await page
        .getByTestId(
          "assistant-message-current"
        )
        .textContent();

    expect(
      after?.startsWith(
        before ?? ""
      )
    ).toBeTruthy();
  }
);
```

---

## 40.12 Running 中 queue follow-up

```typescript
test(
  "composer remains usable while task runs",
  async ({ page }) => {
    await startLongTask(
      page
    );

    const composer =
      page.getByPlaceholder(
        /follow-up/i
      );

    await expect(
      composer
    ).toBeEnabled();

    await composer.fill(
      "Also make the sidebar narrower"
    );

    await page
      .getByRole(
        "button",
        {
          name:
            /queue/i,
        }
      )
      .click();

    await expect(
      page.getByText(
        /queued/i
      )
    ).toBeVisible();
  }
);
```

---

## 40.13 Continuous edit E2E

这是 PaperForge 下一阶段最重要的业务测试。

```typescript
test(
  "generated app can be edited in the next turn without reparsing the paper",
  async ({ page }) => {
    await seedGeneratedRun(
      page
    );

    await page
      .getByPlaceholder(
        /Ask PaperForge/
      )
      .fill(
        "Make the sidebar narrower"
      );

    await page
      .getByRole(
        "button",
        { name: /send/i }
      )
      .click();

    await expect(
      page.getByText(
        /Inspecting workspace/i
      )
    ).toBeVisible();

    // 不应该重新跑 paper parser。
    await expect(
      page.getByText(
        /Reading paper/i
      )
    ).not.toBeVisible();

    await expect(
      page.getByText(
        /files changed/i
      )
    ).toBeVisible();
  }
);
```

---

# 41. 推荐 PR 顺序

## PR 0 — Integration Blockers

修改：

```text
ToolContext.task_id
EventEmitter default task_id
nextjs_app workspace restore
workspace tool definitions/dispatcher
Anthropic tool stream correctness
Browser Smoke route/action
```

**验收：**

```text
pytest integration tests 全通过
真实 run 不在 ToolContext 构造阶段报错
已有 app 可以 inspect/read/patch
```

---

## PR 1 — Resource Runtime

修改：

```text
Resource Gate authoritative
删除 Phase Gate permission
删除 DONE → INIT
Run = thread
Task = request
```

**验收：**

```text
生成完成后下一条消息能直接改 workspace
不会重新 parse
```

---

## PR 2 — Realtime Contract V2

修改：

```text
EventEmitter task_id
SSE v2 envelope
default onmessage
unknown ignored
true gap only hydrate
rAF delta batching
stable message key
smart scroll
```

**验收：**

```text
streaming E2E
reload E2E
future event test
gap test
```

---

## PR 3 — Queue / Interrupt

修改：

```text
MessageCreate.mode
scheduler
running composer
optimistic public_id
queue button
interrupt action
```

**验收：**

```text
running 中能输入
queue 不丢消息
interrupt 不丢附件
workspace 保留
```

---

## PR 4 — Task Steps / Turn Data

修改：

```text
task_steps table
messages.task_id
artifact/event task_id
ProgressReporter
step events
```

**验收：**

```text
每个 task 的 steps 可以独立查询
reload 后 step timeline 不丢
```

---

## PR 5 — Conversation UI

修改：

```text
Turn projection
inline StepGroup
inline Approval
inline Artifacts
remove AgentActivity global log
remove duplicate RunHeader
remove permanent quick actions
```

**验收：**

```text
连续三轮交互仍能看清每轮 Agent 做了什么
```

---

## PR 6 — Adaptive Workbench

修改：

```text
closed / peek / open
remove permanent 42/58 split
PreviewPanel modularization
Changes/Test/Logs presentation
```

**验收：**

```text
无 preview 不出现巨大空白
file.changed → peek
preview.ready → open
用户可关闭并保持
```

---

## PR 7 — Generation V3

修改：

```text
workspace_planner prompt
plan-only call
batch generator
dependency-aware context
per-batch revision
per-batch progress
```

**验收：**

```text
复杂 app 不依赖单个巨大 JSON
单一 batch 可以 retry
```

---

## PR 8 — Verification V3

修改：

```text
hard gates
AcceptanceExecutor
targeted repair
WorkspacePatch repair
stream command runner
```

**验收：**

```text
TypeScript error 不能因为 score 高而 ready
must criterion failure 不能 product_ready
```

---

## PR 9 — Production Runtime

修改：

```text
durable scheduler
lease worker
EventBroker
preview origin
sandbox limits
```

---

## PR 10 — Cleanup / Docs / Types

修改：

```text
remove obsolete Phase permission code
remove named SSE handlers
remove legacy Quick Actions
OpenAPI types
docs / ADR
```

---

# 42. 文件级修改清单

## Backend — 立即修改

### `paperforge/orchestrator/loop.py`

```text
P0:
- 修 ToolContext contract

P1:
- 删除 ALLOWED_TOOLS authoritative gate
- EventEmitter(task_id=...)
- 后续切 ProviderStreamEvent
```

### `paperforge/orchestrator/tools.py`

```text
P0:
+ ToolContext.task_id
+ inspect_workspace
+ read_workspace_file
+ apply_workspace_patch
+ run_checks
+ handlers registry

P1:
+ ProgressReporter wrapper
```

### `paperforge/orchestrator/workspace.py`

```text
P0:
+ recognize nextjs_app
+ metadata.app_path
+ sandbox state

P1:
+ requires_all / requires_any
```

### `paperforge/llm/anthropic_provider.py`

```text
P0:
+ preserve tool calls

P1:
+ provider-neutral native stream
```

### `paperforge/llm/base.py`

```text
P1:
+ ProviderStreamEvent
+ stream_events protocol
```

### `api/routes/messages.py`

```text
P1:
+ mode start/queue/interrupt
+ Field(default_factory=list)
- running 409 as only behavior
- DONE → INIT
+ task/message IDs linkage
```

### `paperforge/orchestrator/tasks.py`

```text
P1:
+ scheduler uses durable Task rows

P2:
+ lease worker
```

### `paperforge/orchestrator/events.py`

```text
P1:
+ default task_id
+ step events
+ file.changed
+ build/test events

P2:
+ EventBroker abstraction
```

### `api/routes/events.py`

```text
P1:
+ version
+ task_id
+ single SSE message envelope
- named event transport
```

### `paperforge/agents/browser_smoke.py`

```text
P0:
+ route field
+ action
+ input_value
+ correct expected semantics
+ not_applicable
```

### `paperforge/agents/verifier.py`

```text
P1:
+ hard gates
+ product_ready
+ targeted files
+ shared patch engine
+ real streaming command runner
```

### `paperforge/agents/nextjs_generator.py`

```text
P1/P2:
- one giant plan+files response
+ plan call
+ batch generation
+ context selection
+ per-batch revision
```

---

## Frontend — 立即修改

### `web/components/Composer.tsx`

```text
+ submitMessage(mode)
+ running input
+ queue/interrupt
+ public_id
+ user status=completed
- permanent QUICK_ACTIONS
```

### `web/components/ChatPanel.tsx`

```text
- smooth scroll on messages/events
- key=index
- detached AgentActivity
- duplicate RunHeader

+ Conversation/Turn
+ smart scroll
+ JumpToLatest
```

### `web/lib/run-events.ts`

```text
+ ignored result
+ rAF buffering
+ steps
+ file.changed
- unknown→hydrate
```

### `web/lib/useRunSession.ts`

```text
- EVENT_TYPES registration
+ one RunStream.onmessage
+ only gap hydrate
```

### `web/lib/api.ts`

```text
+ SSE envelope v2
+ MessageCreate.mode
+ generated API types
```

### `web/lib/store.ts`

```text
+ debug ring buffer
+ task/step state

之后拆:
conversation/task/workbench/ui
```

### `web/app/runs/[id]/page.tsx`

```text
- fixed desktop 42/58
+ adaptive workbench
```

### `web/components/PreviewPanel.tsx`

```text
拆分删除 God Component
```

---

# 43. 删除旧路径清单

这一项非常重要。

如果只新增不删除，PaperForge 还会继续变复杂。

完成新路径后明确删除：

```text
ALLOWED_TOOLS 作为权限系统
DONE → INIT reset
running message 只能 409 的旧逻辑
named SSE EVENT_TYPES
unknown event → hydrate
Composer isRunning disable
user optimistic streaming=true
message key=index
ChatPanel smooth-scroll-every-event
global AgentActivity(last 20)
permanent 5 Quick Actions
fixed 42/58 desktop layout
monolithic plan+files generation path
repair direct file write path
score>=0.6 作为唯一 readiness gate
```

Provider normalization 完成后删除：

```text
provider-specific Chunk accumulation
```

只保留一个统一 stream path。

---

# 44. 最终 Definition of Done

## Realtime

- [ ] 用户发送后 Assistant 在任务完成前开始出现；
- [ ] 不刷新也可持续看到输出；
- [ ] 后端仍使用 StreamWriter coalesce；
- [ ] 前端 rAF batching；
- [ ] reload/reconnect 不重复文字；
- [ ] unknown future event 不触发 full hydrate；
- [ ] 只有真实 seq gap 才 hydrate；
- [ ] 用户向上滚后不会被强制拉到底；
- [ ] 有 Jump to latest。

## Agent Runtime

- [ ] `ToolContext` contract 无错位；
- [ ] workspace tools 在 schema / resource / dispatcher 三处一致；
- [ ] `nextjs_app` 能恢复 workspace；
- [ ] Resource Gate 是唯一 tool prerequisite 权威；
- [ ] RunPhase 不再决定工具权限；
- [ ] completed task 后可继续编辑；
- [ ] 不需要重新 parse paper；
- [ ] running 时支持 queue；
- [ ] 支持 interrupt；
- [ ] 每个 task 有 durable steps。

## Provider

- [ ] OpenAI tool stream 正确；
- [ ] Anthropic tool stream 正确；
- [ ] 最终统一 provider stream event；
- [ ] Orchestrator 不知道 provider-specific delta shape。

## Generation

- [ ] multi-file 保留；
- [ ] SafeWorkspacePolicy 保留；
- [ ] 计划与代码生成拆开；
- [ ] 代码按 logical batch 生成；
- [ ] 每 batch 有 revision；
- [ ] 每 batch 有 progress；
- [ ] 失败只 retry relevant batch；
- [ ] 后续 task 可以 patch 现有 workspace。

## Verification

- [ ] route criterion 使用 `route`；
- [ ] interaction 执行真实 `action`；
- [ ] fill/select/upload 使用 `input_value`；
- [ ] Must criteria 失败不会 product_ready；
- [ ] no criteria 不伪装成 passed；
- [ ] TypeScript hard failure 不会被 score 抵消；
- [ ] Repair 只读取 relevant files；
- [ ] Repair patch 经过同一 SafeWorkspacePolicy；
- [ ] build/typecheck logs 可实时展示。

## Conversation UI

- [ ] Run 只显示一个 TopBar；
- [ ] 每个 Task 是一个 Turn；
- [ ] Step 与对应 Turn inline；
- [ ] Approval 与对应 Turn inline；
- [ ] Artifact 与对应 Task 有归属；
- [ ] 不再有全局 AgentActivity 调试块；
- [ ] running 时 Composer 可输入；
- [ ] Quick Actions 不永久堆叠；
- [ ] user message optimistic ID 和 server `public_id` 一致；
- [ ] completed history messages 不反复 render。

## Workbench

- [ ] 无 workspace 时 closed；
- [ ] file change 后 peek；
- [ ] preview.ready 后 open；
- [ ] 用户手动关闭后不抢回来；
- [ ] PreviewPanel 拆分；
- [ ] Code / Changes / Tests / Artifacts / Logs 模块独立；
- [ ] Verification 直接显示失败 criterion 和 Fix action。

## Production

- [ ] stale task 可被 worker reclaim；
- [ ] 多 worker live event 有 Broker；
- [ ] preview 与 main app 不同 origin；
- [ ] sandbox 有资源限制；
- [ ] network 默认受控；
- [ ] Metrics 能测 TTFT / task duration / build / acceptance。

---

# 45. 审查依据

本方案是基于 **2026-08-11 当前 GitHub `main` 分支**重新审查后整理，而不是复用旧 review 结论。

重点核对文件：

```text
paperforge/orchestrator/loop.py
paperforge/orchestrator/tools.py
paperforge/orchestrator/workspace.py
paperforge/orchestrator/stream_writer.py
paperforge/orchestrator/events.py
paperforge/orchestrator/tasks.py

paperforge/llm/base.py
paperforge/llm/openai_provider.py
paperforge/llm/anthropic_provider.py

paperforge/agents/nextjs_generator.py
paperforge/agents/verifier.py
paperforge/agents/browser_smoke.py
paperforge/agents/paper_parser.py

paperforge/schemas/prd.py
paperforge/schemas/app_manifest.py
paperforge/schemas/workspace_plan.py

api/routes/messages.py
api/routes/events.py

web/components/ChatPanel.tsx
web/components/Composer.tsx
web/components/PreviewPanel.tsx

web/lib/api.ts
web/lib/store.ts
web/lib/run-events.ts
web/lib/useRunSession.ts

web/app/runs/[id]/page.tsx
```

Repository:

```text
https://github.com/Vincent-Wenhan/PaperForge
```

---

# 最后建议

现在 PaperForge 最应该做的已经不是“再设计一套大架构”。

当前代码最大的机会是：

```text
已经写了很多正确的新部件
↓
把它们真正接起来
↓
删掉旧路径
↓
让 Continuous Agent 成为唯一主流程
```

尤其应该优先闭环：

```text
ToolContext
Workspace Tools
WorkspaceState
Resource Gate
Anthropic Tool Stream
Browser Acceptance
```

然后立即进入：

```text
Continuous Agent
+
Turn UI
+
Adaptive Workbench
```

等这三层完成之后，再做 Generation V3 和 production runtime。

如果按这个顺序推进，PaperForge 的变化不会只是“界面更像 ChatGPT/Codex”，而会从底层交互模型上真正变成：

> **一个可以围绕论文持续理解、生成、修改、验证和预览软件产品的 Agent Workspace。**
