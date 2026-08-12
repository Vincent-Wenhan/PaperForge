# PaperForge 最新全仓库复审与收口实现方案

> **复审日期：2026-08-11**  
> **复审基线：GitHub `main` 最新公开提交 `0aa84cb`**  
> **仓库：** `Vincent-Wenhan/PaperForge`  
> **目标：** 核对前几轮重构方案到底哪些已经真正进入主链、哪些只是“代码存在但未接通”、哪些仍存在明确 Bug，并给出下一轮可以直接施工的实现方案。  
> **结论：** PaperForge 的架构主体已经比早期完整很多，但**目前仍不能称为“完整实现”**。当前主要问题已经从“缺功能”转变为“领域状态一致性、主链收口、旧路径删除和运行时可靠性”。

---

# 1. Executive Summary

当前 `main@0aa84cb` 已经真正实现了不少前几轮方案：

```text
✓ StreamWriter + 流式 checkpoint
✓ ProviderStreamEvent 主链
✓ durable run_events + per-run seq
✓ SSE replay / single onmessage
✓ Resource Gate
✓ WorkspaceState / SafeWorkspacePolicy
✓ Workspace Tools
✓ PRD V2 / Browser Acceptance action executor
✓ Queue / Interrupt
✓ Task + Step
✓ Turn Projection
✓ Adaptive Workbench closed/peek/open
✓ Verification hard-gate fields
✓ Targeted repair
✓ Generation V3 implementation file
✓ worker lease fields
✓ metrics / sandbox hardening
```

但是逐条检查**实际主调用路径**后，仍存在这些关键断点：

```text
1. User Message 的 task_id 与真正 Task.id 不一致
2. Streaming assistant message 没有 task_id
3. Tool result message 没有 task_id
4. Artifact / Approval 数据模型没有 task_id
5. finish 仍然把整个 Run 设成 done
6. 下一轮 Orchestrator 发现 run.done 会直接 return
7. generation_v3.py 已存在，但 handle_generate 仍调用旧 V2 generator
8. RunQueue 按 run 排队，但 claim_next_task() 全局 claim 最老 Task
9. Queue 中仍保存 Python coroutine，重启后无法真正恢复执行
10. Verifier 已算 technical_ready / preview_allowed / product_ready，
    但 Tool Handler 仍以 ready_for_preview 决定成功失败
11. Turn Projection 已写，但 1~4 会导致大量实体落入 untracked
12. Workbench 自适应已实现，但 PreviewPanel 仍约 902 行
13. OpenAPI schema 已生成，真实 API client 仍大量手写 type / any
14. Parser 有 ParseCoverage，但仍最多处理前 32 chunks / 前 16 map chunks
15. EventBroker interface 已存在，但 EventManager 主链没有使用 Broker
```

所以当前状态可以概括成：

> **“模块级重构基本完成，领域一致性和运行时主链收口仍未完成。”**

下一轮应该严格按：

```text
Domain Correctness
→ Persistent Thread
→ Scheduler Correctness
→ Generation/Verification 主链收口
→ Turn UI Closure
→ Workbench/Parser/Production Runtime
```

推进，而不是继续新增更多功能。

---

# 2. 当前真实实现状态矩阵

| 模块 | 当前状态 | 是否真正进入主链 |
|---|---|---|
| StreamWriter | 已实现 | ✅ |
| ProviderStreamEvent | 已实现 | ✅ |
| SSE replay / seq | 已实现 | ✅ |
| Single SSE `onmessage` | 已实现 | ✅ |
| frontend rAF stream buffer | 已实现 | ✅ |
| Resource Gate | 已实现 | ✅ |
| Workspace Tools | 已实现 | ✅ |
| Queue / Interrupt | 已实现 | ✅，但 scheduler 有 Bug |
| Task / Step | 已实现 | ✅ |
| Turn Projection | 已实现 | ⚠️ task_id 数据链断裂 |
| Adaptive Workbench | 已实现 | ✅ |
| Generation V3 | 已实现文件 | ❌ 未接 `handle_generate` |
| Verification V3 gates | 已实现 | ⚠️ 旧 readiness 仍掌权 |
| Durable Worker | lease 有 | ❌ Queue 仍依赖 coroutine |
| CapabilityContract | schema 有 | ❌ Parser 仍输出 CapabilityCard |
| EventBroker | interface 有 | ❌ EventManager 未使用 |
| OpenAPI TS | schema 生成 | ❌ API client 未真正采用 |
| Workbench components | 未拆 | ❌ PreviewPanel 仍 902 行 |

---

# 3. P0 问题总表

| 优先级 | 问题 | 直接影响 |
|---|---|---|
| P0 | User Message.task_id != Task.id | Turn UI 错绑 |
| P0 | `finish → run.done` | 下一轮 follow-up 可能不执行 |
| P0 | Generation V3 未接主链 | 复杂 App 仍走巨大 JSON |
| P0 | `claim_next_task()` 全局抢 oldest | 多 Run 并发可能错领任务 |
| P0 | Queue 保存 coroutine | 重启后任务无法真正恢复 |
| P0 | Assistant/Tool/Artifact/Approval task_id 缺失 | Turn reload 不完整 |
| P0 | Tool Handler 仍使用 `ready_for_preview` | Hard Gates 不权威 |

---

# 4. P0-1：Task ID 断裂

## 当前问题

Messages API 先生成：

```python
task_id = f"task_{uuid.uuid4().hex}"

message = storage.add_message(
    run_id=run_id,
    role="user",
    content=req.content,
    public_id=req.public_id,
    task_id=task_id,
)
```

但随后：

```python
task = storage.create_task(...)
```

而 `Storage.create_task()` 内部又：

```python
task_id = f"task_{uuid.uuid4().hex}"
```

于是：

```text
User Message.task_id = task_A
真正 Task.id         = task_B
```

`projectTurns()` 又严格按：

```typescript
message.task_id === task.id
```

分组，所以当前 Turn Projection 从数据层就不稳定。

## 修复

让 `create_task()` 接收显式 ID：

```python
def create_task(
    self,
    run_id: str,
    title: str | None = None,
    goal: str | None = None,
    status: str = "queued",
    phase: str = "init",
    priority: int = 0,
    user_message_id: int | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    now = datetime.utcnow().isoformat()

    task_id = (
        task_id
        or f"task_{uuid.uuid4().hex}"
    )

    with self._lock, self._conn() as conn:
        conn.execute(
            """
            INSERT INTO tasks (
                id, run_id, title, goal,
                status, phase, priority,
                user_message_id,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                run_id,
                title,
                goal,
                status,
                phase,
                priority,
                user_message_id,
                now,
                now,
            ),
        )

    return self.get_task(task_id)
```

Messages API：

```python
task_id = f"task_{uuid.uuid4().hex}"

message = storage.add_message(
    run_id=run_id,
    role="user",
    content=req.content,
    public_id=req.public_id,
    task_id=task_id,
)

task = storage.create_task(
    task_id=task_id,
    run_id=run_id,
    title=req.content[:120],
    goal=req.content,
    status="queued",
    phase=storage.get_run_phase(run_id) or "init",
    priority=100 if req.mode == "interrupt" else 0,
    user_message_id=message["id"],
)
```

更进一步建议把 Message+Task 创建放到同一 DB transaction，避免“Message 已写但 Task 创建失败”的孤立数据。

---

# 5. P0-2：`finish → run.done` 仍破坏 Persistent Thread

Messages API 已经明确把 Run 定义成 persistent thread，但 Orchestrator 开头仍：

```python
prev_status = (
    self.storage.get_run_status(run_id)
    or "active"
)

if prev_status in {
    "cancelled",
    "done",
}:
    return
```

同时 `handle_finish()`：

```python
return ToolResult(
    tool="finish",
    status=ToolStatus.SUCCEEDED,
    data={
        "summary": summary,
        "status": "done",
    },
    summary=summary,
    next_phase="done",
    stop_loop=True,
)
```

Main loop 遇到 `RunPhase.DONE` 又把：

```text
Run.status = done
Task.status = completed
```

因此：

```text
Task 1 finish
→ Run.done

Task 2 queued
→ Orchestrator.run()
→ prev_status == done
→ return
```

## 正确领域模型

```text
Run / Thread:
active
running
waiting_user
error
archived

Task:
queued
running
waiting_user
waiting_approval
completed
failed
cancelled
```

**Task completed ≠ Run completed。**

## 修改 `finish`

```python
async def handle_finish(
    args: dict[str, Any],
    ctx: ToolContext,
) -> ToolResult:
    summary = (
        args.get("summary")
        or "Task completed"
    )

    return ToolResult(
        tool="finish",
        status=ToolStatus.SUCCEEDED,
        data={
            "summary": summary,
            "task_status": "completed",
        },
        summary=summary,
        next_phase=None,
        stop_loop=True,
    )
```

Main loop：

```python
if stop_loop:
    waiting_for_user = (
        stopped_result
        and stopped_result.code
            == "needs_user_input"
    )

    if waiting_for_user:
        self._update_task(
            status="waiting_user"
        )
        run_status = "waiting_user"
    else:
        self._update_task(
            status="completed"
        )
        run_status = "active"

    previous = (
        self.storage
        .get_run_status(run_id)
        or "running"
    )

    self.storage.update_run_status(
        run_id,
        run_status,
    )

    await emit.run_status_changed(
        run_status,
        previous,
    )

    await emit.run_updated(
        status=run_status
    )

    await emit.run_finished()
    return
```

建议长期删除：

```text
RunPhase.DONE
Run.status == done
```

作为 Thread terminal。

真正的 Thread terminal 应该是：

```text
archived_at != null
```

---

# 6. P0-3：Generation V3 已写但未接主链

仓库已经有：

```text
paperforge/agents/generation_v3.py
```

并实现：

```text
plan_workspace
group_plan_files
generate_batch
dependency-aware context
```

但是当前真实 `handle_generate()` 仍：

```python
from paperforge.agents.nextjs_generator \
    import generate_nextjs_app

manifest = await generate_nextjs_app(...)
```

而 `nextjs_generator.py` 仍是：

```text
一次 LLM 调用
→ plan + 全部 files + manifest
```

所以目前：

```text
Generation V3 Implementation ✓
Generation V3 Wiring         ✗
```

## 推荐正式入口

```python
async def generate_nextjs_app_v3(
    *,
    prd_id: str,
    output_dir: str | Path,
    llm: LLMClient,
    storage: Storage,
    progress=None,
) -> dict[str, Any]:
    artifact = storage.get_artifact(
        prd_id
    )

    if not artifact:
        raise ValueError(
            f"PRD not found: {prd_id}"
        )

    prd = artifact.get("data") or {}

    output_dir = Path(
        output_dir
    ).resolve()

    temp_dir = (
        create_scaffold_temp_dir(
            output_dir
        )
    )

    try:
        plan = await plan_workspace(
            prd=prd,
            llm=llm,
        )

        generated_files = []

        for kind, specs in (
            group_plan_files(plan)
        ):
            step_id = None

            if progress:
                step_id = (
                    await progress.start(
                        kind="codegen",
                        title=(
                            f"Generating {kind}"
                        ),
                    )
                )

            batch = await generate_batch(
                prd=prd,
                plan=plan,
                specs=specs,
                workspace_root=temp_dir,
                llm=llm,
            )

            changed = write_batch_files(
                root=temp_dir,
                batch=batch,
            )

            generated_files.extend(
                changed
            )

            if progress and step_id:
                await progress.complete(
                    step_id,
                    summary=(
                        f"{len(changed)} "
                        "files generated"
                    ),
                )

        merge_safe_dependencies(
            temp_dir,
            plan.dependencies,
        )

        validate_generated_workspace(
            temp_dir,
            plan,
        )

        atomic_promote_workspace(
            temp_dir,
            output_dir,
        )

    except Exception:
        shutil.rmtree(
            temp_dir,
            ignore_errors=True,
        )
        raise

    return {
        "app_id": (
            f"app_{uuid.uuid4().hex}"
        ),
        "plan": plan.model_dump(),
        "files": generated_files,
        "output_dir": str(output_dir),
    }
```

然后：

```python
handle_generate()
→ generation_v3.generate_nextjs_app_v3()
```

V3 稳定后删除旧的 single-call main path。

---

# 7. P0-4：RunQueue 存在跨 Run 错领任务问题

当前 Queue 按 Run 分：

```python
self._queues[
    run_id
]
```

Worker 已经知道：

```text
run_id
task_id
```

但 claim 时调用：

```python
storage.claim_next_task(...)
```

SQL 却是：

```sql
SELECT *
FROM tasks
WHERE status = 'queued'
ORDER BY created_at ASC
LIMIT 1
```

没有：

```text
run_id
task_id
```

之后才检查：

```python
if (
    not claimed
    or claimed["id"] != task_id
):
    return False
```

问题是被错误选中的 Task **已经被更新为 running**。

## 修复：exact claim

```python
def claim_task(
    self,
    *,
    task_id: str,
    worker_id: str,
    lease_until: str,
) -> dict[str, Any] | None:
    with self._lock, self._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")

        try:
            row = conn.execute(
                """
                SELECT *
                FROM tasks
                WHERE id = ?
                  AND status = 'queued'
                """,
                (task_id,),
            ).fetchone()

            if not row:
                conn.execute("COMMIT")
                return None

            conn.execute(
                """
                UPDATE tasks
                SET
                    status = 'running',
                    lease_owner = ?,
                    lease_until = ?,
                    started_at = COALESCE(
                        started_at,
                        CURRENT_TIMESTAMP
                    ),
                    attempt = attempt + 1
                WHERE id = ?
                  AND status = 'queued'
                """,
                (
                    worker_id,
                    lease_until,
                    task_id,
                ),
            )

            conn.execute("COMMIT")

        except Exception:
            conn.execute("ROLLBACK")
            raise

    return self.get_task(task_id)
```

Queue 改：

```python
claimed = storage.claim_task(
    task_id=task_id,
    worker_id=worker_id,
    lease_until=(
        lease_until.isoformat()
    ),
)
```

---

# 8. P0-5：当前 Queue 仍不是真正 Durable

当前 Queue 元素：

```python
tuple[
    task_id,
    Coroutine
]
```

也就是：

```python
orchestrator.run(...)
```

这个 coroutine 不能持久化。

Backend restart 后虽然：

```python
storage.reconcile_stale_tasks()
```

能把 stale running 改回 queued，但**没有 coroutine 可以继续执行它**。

## 最终 Queue 只存 Task ID

```python
class RunQueue:
    def __init__(
        self,
        storage: Storage,
        orchestrator_factory,
    ):
        self.storage = storage
        self.orchestrator_factory = (
            orchestrator_factory
        )

        self._queues: dict[
            str,
            asyncio.Queue[str],
        ] = {}

    async def enqueue(
        self,
        run_id: str,
        task_id: str,
    ):
        queue = (
            self._queues.setdefault(
                run_id,
                asyncio.Queue(),
            )
        )

        await queue.put(task_id)
```

执行时 DB 恢复：

```python
async def execute_task(
    self,
    task_id: str,
):
    task = self.storage.get_task(
        task_id
    )

    if not task:
        return

    orchestrator = (
        self.orchestrator_factory()
    )

    await orchestrator.run(
        run_id=task["run_id"],
        user_message=(
            task.get("goal")
            or ""
        ),
        task_id=task_id,
    )
```

Startup：

```python
storage.reconcile_stale_tasks()

for task in (
    storage.list_queued_tasks()
):
    await scheduler.enqueue(
        task["run_id"],
        task["id"],
    )
```

这才叫真正的 restart recovery。

---

# 9. P0-6：Task 归属仍未完整贯通

Turn Projection 当前依赖：

```text
message.task_id
step.task_id
approval.task_id
artifact.task_id
```

但实际只有部分实体持久化 task_id。

## 9.1 Streaming Assistant

当前：

```python
def create_streaming_message(
    self,
    run_id,
    public_id,
):
    return self.add_message(
        ...,
        status="streaming",
    )
```

应改：

```python
def create_streaming_message(
    self,
    run_id: str,
    public_id: str,
    *,
    task_id: str | None = None,
):
    return self.add_message(
        run_id=run_id,
        role="assistant",
        content="",
        public_id=public_id,
        status="streaming",
        task_id=task_id,
    )
```

Orchestrator：

```python
self.storage.create_streaming_message(
    run_id,
    message_id,
    task_id=self.task_id,
)
```

## 9.2 Tool Message

当前 Tool result 保存没有 task_id。

修：

```python
self.storage.add_message(
    run_id=run_id,
    role="tool",
    content=result_str,
    tool_call_id=call.id,
    name=call.name,
    task_id=self.task_id,
)
```

## 9.3 Final Assistant

```python
self.storage.add_message(
    run_id=run_id,
    role="assistant",
    content=final_content,
    task_id=self.task_id,
)
```

## 9.4 Artifact

新增 DB：

```sql
ALTER TABLE artifacts
ADD COLUMN task_id TEXT;
```

API：

```python
save_artifact(
    ...,
    task_id=ctx.task_id,
)
```

## 9.5 Approval

```sql
ALTER TABLE approvals
ADD COLUMN task_id TEXT;
```

创建：

```python
create_approval(
    run_id=run_id,
    task_id=self.task_id,
    ...
)
```

## 9.6 Event → Store

EventEmitter 已经正确绑定 `event.task_id`。

前端创建实体时应该：

```typescript
task_id:
  data.task_id
  ?? event.task_id
  ?? undefined
```

尤其：

```text
message.started
artifact.created
approval.requested
```

都要做。

---

# 10. P0-7：Verification Hard Gates 还不是最终权威

Verifier 当前已经正确计算：

```text
technical_ready
preview_allowed
product_ready
```

但 `handle_verify()` 和 `handle_build_and_repair()` 仍：

```python
ready = bool(
    report.get(
        "ready_for_preview"
    )
)
```

并用它决定 Tool Success/Failure。

所以：

```text
Hard Gate fields       ✓
Hard Gate orchestration ✗
```

## 正式收口

Tool 本身执行成功：

```python
status = ToolStatus.SUCCEEDED
```

报告表达是否 Ready：

```python
technical_ready = bool(
    report.get("technical_ready")
)

preview_allowed = bool(
    report.get("preview_allowed")
)

product_ready = bool(
    report.get("product_ready")
)
```

返回：

```python
return ToolResult(
    tool="verify_app",
    status=ToolStatus.SUCCEEDED,
    artifact_id=artifact_id,
    data={
        "report": report,
        "technical_ready":
            technical_ready,
        "preview_allowed":
            preview_allowed,
        "product_ready":
            product_ready,
    },
    summary=(
        "Verification completed: "
        f"technical_ready="
        f"{technical_ready}, "
        f"product_ready="
        f"{product_ready}"
    ),
    next_phase=(
        "verified"
        if technical_ready
        else None
    ),
)
```

`ready_for_preview` 可以暂时保留为兼容 derived field，但新逻辑不再依赖它。


# 11. P1：Realtime Pipeline 当前完成度

Realtime 已经不是当前主 blocker。

## 已完成

```text
✓ StreamWriter
✓ message checkpoint
✓ ProviderStreamEvent
✓ EventEmitter task_id
✓ durable run_events
✓ after_seq replay
✓ single onmessage
✓ frontend stream-buffer
✓ real gap → hydrate
✓ unknown event 不强制 hydrate
```

这部分建议只继续做：

```text
entity task_id propagation
performance metrics
long-message rendering optimization
```

---

# 12. ProviderStreamEvent 当前状态

`loop.py` 当前已经真正：

```python
stream_events = getattr(
    self.llm,
    "stream_events",
    None,
)

async for ev in stream_events(...):
    if ev.kind == "text_delta":
        ...
    elif ev.kind == "tool_done":
        ...
```

所以 Provider-neutral stream 已经进入主链。

这部分不要再重构一套新的 Provider protocol。

只需要补：

```text
provider contract tests
malformed tool args handling
usage/tokens metrics
```

---

# 13. Resource Gate 当前状态

当前 Resource Gate 已经是真正权限主路径。

`RunPhase` 当前注释也已经说明：

```text
for UI display only
```

这是正确方向。

不过 `check_tool_prerequisites()` 当前：

```python
if spec is None:
    return True, []
```

安全模型更推荐 fail closed：

```python
if spec is None:
    return (
        False,
        ["unknown_tool"],
    )
```

并增加 registry consistency test：

```python
def test_tool_registry_consistency():
    definitions = {
        definition.name
        for definition
        in TOOL_DEFINITIONS
    }

    dispatchers = set(
        TOOL_HANDLERS
    )

    assert definitions == dispatchers

    resource_tools = (
        definitions
        - CONTROL_TOOLS
    )

    assert (
        resource_tools
        <= set(TOOL_SPECS)
    )
```

这样未来不会再次出现：

```text
Tool Definition 有
Resource Gate 没有

或

Resource Gate 有
Dispatcher 没有
```

---

# 14. Queue / Interrupt 当前状态

Composer 当前已经完成：

```text
start
queue
interrupt
optimistic public_id
running 中继续输入
user message streaming=false
```

所以前端发送层不用重写。

当前剩余都是 Scheduler/Domain 问题：

```text
task id mismatch
global claim
coroutine queue
restart recovery
run.done
```

这些修完以后 Queue/Interrupt 才算真正完整。

---

# 15. Conversation / Turn UI 当前状态

当前已有：

```typescript
projectTurns(
  tasks,
  messages,
  steps,
  approvals,
  artifacts,
)
```

而且 ChatPanel 已经使用。

所以这一块的方向已经对。

真正 blocker 是后端实体 task_id 不完整。

修完 Task Domain 后，Turn UI 才会从：

```text
UI projection demo
```

变成：

```text
可靠 conversation model
```

建议 `untracked` 仅保留给历史数据库：

```typescript
const legacyUntracked =
  isLegacyData
    ? ...
    : [];
```

新数据如果出现 untracked，应在 development 模式直接 warning：

```typescript
if (
  process.env.NODE_ENV
  !== "production"
  && untracked.length
) {
  console.warn(
    "Unexpected untracked "
    "conversation entities",
    untracked,
  );
}
```

这样 task_id regression 会更早暴露。

---

# 16. Jump to Latest React 状态 Bug

当前：

```typescript
const jumpRef =
  useRef({
    visible: false,
  });

jumpRef.current.visible =
  !nearBottom;
```

然后 JSX 判断：

```tsx
jumpRef.current.visible
```

`ref.current` 更新不会触发 render。

改：

```typescript
const [
  showJumpToLatest,
  setShowJumpToLatest,
] = useState(false);

const onScroll = () => {
  const el =
    scrollRef.current;

  if (!el) return;

  const nearBottom =
    (
      el.scrollHeight
      - el.scrollTop
      - el.clientHeight
    ) < 96;

  pinnedToBottom.current =
    nearBottom;

  setShowJumpToLatest(
    !nearBottom
  );
};
```

Jump：

```typescript
const jumpToLatest =
  () => {
    const el =
      scrollRef.current;

    if (!el) return;

    el.scrollTo({
      top: el.scrollHeight,
      behavior: "smooth",
    });

    pinnedToBottom.current =
      true;

    setShowJumpToLatest(
      false
    );
  };
```

---

# 17. 重复 Run Header 与工程信息暴露

当前顶层已有：

```text
GlobalHeader
```

ChatPanel 仍渲染：

```text
RunHeader
title
runId
status
phase
artifact count
```

这使 UI 继续像：

```text
Agent Debug Dashboard
```

建议删除 ChatPanel `RunHeader`。

GlobalHeader 保留：

```text
PaperForge / Run Title
● Running
...
```

内部数据：

```text
run id
task id
phase
event cursor
sandbox id
```

放到：

```text
··· → Run details
```

---

# 18. Workbench 已 Adaptive，但 `PreviewPanel.tsx` 仍约 902 行

当前：

```text
closed → hidden
peek → 360px
open → min(56vw, 1040px)
```

已经真正实现。

这一块不需要再重做布局。

但是 `PreviewPanel.tsx` 仍然同时包含：

```text
PreviewFrame
Preview toolbar
Monaco
File tree
Tabs
Save logic
Changes
Revision
Tests
Artifacts
Logs
Sandbox controls
```

建议下一轮先做**纯移动 refactor**，不改行为：

```text
web/components/workbench/

  Workbench.tsx
  WorkbenchHeader.tsx
  WorkbenchTabs.tsx

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
    ArtifactCard.tsx

  logs/
    LogsView.tsx
    LogToolbar.tsx
```

第一步只拆文件，保证行为完全一致。

第二步再优化交互。

---

# 19. OpenAPI Types：生成了但没有真正成为前端 Contract

仓库已有：

```text
web/lib/api/schema.d.ts
```

但真实 `api.ts` 仍：

```typescript
import type {
  Run,
  Message,
  Paper,
  Sandbox,
  Event,
  Approval,
  Artifact,
} from "./store";
```

同时有大量：

```text
any
body?: any
Promise<any>
payload: any
```

所以当前：

```text
OpenAPI generation  ✓
Contract adoption   ✗
```

## 推荐边界

```text
OpenAPI types
= HTTP API truth

Realtime types
= RunEvent truth

Zustand types
= UI projection truth
```

新增：

```text
web/lib/api/types.ts
```

```typescript
import type {
  components,
} from "./schema";

export type ApiRun =
  components[
    "schemas"
  ][
    "RunResponse"
  ];

export type ApiMessage =
  components[
    "schemas"
  ][
    "MessageResponse"
  ];

export type ApiTask =
  components[
    "schemas"
  ][
    "TaskResponse"
  ];
```

不要再让：

```text
Store interface
```

反过来定义 API response。

---

# 20. Parser 仍是 Partial Understanding

当前已经有：

```text
ParseCoverage
processed_pages
omitted_pages
complete
```

这是进步。

但是依然：

```python
MAX_CHUNKS = 32
MAX_MAP_CHUNKS = 16
```

超过 32：

```python
chunks = chunks[:max_chunks]
```

Map 超过 16：

```python
break
```

所以它仍属于：

```text
Explicit Partial Understanding
```

而不是：

```text
Whole-Paper Understanding
```

这不是当前 P0，但长期 productization 质量会受影响。

---

# 21. CapabilityContract 仍未成为 Runtime Contract

当前 Parser 最终还是：

```python
CapabilityCard.model_validate(...)
```

而不是 `CapabilityContract`。

建议下一阶段输出：

```json
{
  "capability_card": {...},
  "capability_contract": {...},
  "parse_coverage": {...}
}
```

其中：

```text
CapabilityCard
= 人类可读理解

CapabilityContract
= Product Planner 可执行输入
```

Contract 至少应包含：

```text
inputs
outputs
preconditions
failure_modes
integration_mode
compute_requirements
implementation_refs
confidence
```

Planner 优先消费 Contract，Card 用于 UI 展示。

---

# 22. EventBroker 仍是 Scaffold

当前：

```text
EventStore Protocol
EventBroker Protocol
InProcessEventBroker
```

都已经定义。

但是 `EventManager` 仍自己管理：

```python
self._subscribers
self._history
self._seq
```

并自己：

```python
q.put_nowait(event)
```

所以：

```text
Broker interface  ✓
Broker runtime    ✗
```

单进程没有问题。

多 worker 时：

```text
Worker A 产生事件
Worker B 持有 SSE
```

将不能实时 fanout。

## 收口

```python
class EventManager:
    def __init__(
        self,
        *,
        store: EventStore,
        broker: EventBroker,
    ) -> None:
        self.store = store
        self.broker = broker

    async def broadcast(
        self,
        event: Event,
    ) -> None:
        durable = await asyncio.to_thread(
            self.store.append,
            event,
        )

        await self.broker.publish(
            durable
        )
```

SSE 统一订阅 Broker。

这样 production 只需要：

```text
InProcessBroker
→ RedisBroker
```

---

# 23. Event persistence failure 的 seq 隐患

当前事件策略：

```text
persist first
→ authoritative seq
```

这是正确的。

但 DB persistence 失败后会 fallback：

```python
self._seq[rid] += 1
event.seq = self._seq[rid]
```

然后仍推给 Browser。

这会产生：

```text
Browser 看到了 seq=N
但 DB 没有 seq=N
```

下一次 DB 恢复时可能出现 replay/seq divergence。

生产建议：

```text
event persistence failure
→ 不要继续伪装 durable stream
```

最简单：

```python
except Exception:
    logger.exception(
        "Event persistence failed"
    )

    raise EventPersistenceError(...)
```

SSE connection 断开，客户端通过 snapshot + cursor 恢复。

比在内存里继续编一个 seq 更安全。

---

# 24. Preview Origin / Sandbox

当前 iframe 已经：

```text
sandbox=
allow-scripts
allow-forms
allow-modals
allow-popups
```

且没有 `allow-same-origin`，安全性比早期明显好。

Sandbox runtime 也已有：

```text
network default-off
resource limits
hardening
```

但是 PreviewFrame 仍直接：

```typescript
api.getPreviewUrl(
  sandbox.id
)
```

如果 production 配置已有独立 preview origin，前端应该优先使用 server 返回：

```typescript
const previewSrc =
  preview?.preview_url
  ?? sandbox?.preview_url
  ?? (
    sandbox?.id
      ? api.getPreviewUrl(
          sandbox.id
        )
      : null
  );
```

这样同一套 UI 可以：

```text
local dev → /api/preview/...
production → isolated preview origin
```

---

# 25. 数据库 Schema / Migration 收敛

当前 canonical `CREATE TABLE messages` 不直接包含：

```text
task_id
```

而后续 migration `_ensure_column()` 再添加。

这种方式兼容旧 DB 没问题。

但当前 canonical schema 最好直接写成“最新形态”：

```sql
messages.task_id
tasks.priority
tasks.user_message_id
steps.started_at
steps.completed_at
artifacts.task_id
approvals.task_id
```

`_ensure_column()` 仅用于：

```text
upgrade old DB
```

这样读 `SCHEMA_SQL_TABLES` 就能知道当前真实模型。

---

# 26. 推荐最终 Runtime Domain

```text
Run / Thread
│
├── Papers
├── Workspace
├── Current Preview
│
└── Tasks
    │
    ├── User Message
    ├── Assistant Messages
    ├── Tool Messages
    ├── Steps
    ├── Approvals
    ├── Artifacts
    └── Verification
```

核心原则：

```text
Run = persistent workspace/thread
Task = one user goal
```

因此：

```text
Task completed
≠
Run completed
```

---

# 27. Task Lifecycle State Machine

建议正式限制：

```python
class TaskStatus(
    str,
    Enum,
):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_USER = (
        "waiting_user"
    )
    WAITING_APPROVAL = (
        "waiting_approval"
    )
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

不要继续混入：

```text
active
```

这种更适合 Run 的状态。

允许转换：

```text
queued → running

running → waiting_user
running → waiting_approval
running → completed
running → failed
running → cancelled

waiting_user → queued
waiting_approval → running
```

Run：

```text
active
running
waiting_user
error
```

Archive 用：

```text
archived_at
```

---

# 28. 最终 Scheduler 方案

最终不要维护：

```text
Coroutine Queue
```

DB 才是唯一任务队列。

Worker claim：

```sql
SELECT t.*
FROM tasks t
WHERE t.status = 'queued'
  AND NOT EXISTS (
      SELECT 1
      FROM tasks active
      WHERE active.run_id = t.run_id
        AND active.status = 'running'
  )
ORDER BY
    t.priority DESC,
    t.created_at ASC
LIMIT 1;
```

Claim 后：

```text
DB task
→ 构造 Orchestrator
→ execute
```

服务重启：

```text
expired lease
→ queued
→ scheduler 自动 claim
```

这才是真正 durable。

---

# 29. 最终 Task-aware 数据模型

所有“一轮任务内产生的实体”统一带：

```text
task_id
```

包括：

```text
messages
steps
artifacts
approvals
events
verification report
```

建议索引：

```sql
CREATE INDEX
idx_messages_task
ON messages(task_id, id);

CREATE INDEX
idx_artifacts_task
ON artifacts(task_id, created_at);

CREATE INDEX
idx_approvals_task
ON approvals(task_id, created_at);
```

以后甚至可以直接提供：

```text
GET /api/tasks/{task_id}/timeline
```

而不需要前端自己拼很多 endpoint。

---

# 30. Generation V3 正式接入后的 UI Progress

Generation 不应再只显示：

```text
Generating Next.js app...
```

应该：

```text
✓ Planned workspace
✓ Generated types
✓ Generated adapters
● Generating components 6/9
○ Generating routes
○ Running typecheck
```

每个 batch：

```text
revision
file.changed
step.progress
```

都应该产生 event。

这样 Workbench 能边生成边出现文件。

---

# 31. Verification V3 正式收口

最终只保留：

```text
technical_ready
preview_allowed
product_ready
```

如果保留：

```text
ready_for_preview
```

只作为：

```python
ready_for_preview = (
    preview_allowed
)
```

的兼容字段。

前端 Tests：

```text
Technical
✓ Workspace
✓ Typecheck
✓ Build
✓ Security

Runtime
✓ Preview

Acceptance
✗ 4 / 5

Product Ready
No
```

失败 criterion 旁直接：

```text
[Ask PaperForge to fix]
```

---

# 32. Conversation / Turn UI 最终结构

修完 task_id 后，ChatPanel 只渲染：

```tsx
{turns.map(
  turn => (
    <Turn
      key={turn.id}
      turn={turn}
    />
  )
)}
```

Turn：

```tsx
function Turn({
  turn,
}: {
  turn: ConversationTurn;
}) {
  return (
    <section className="py-6">
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
          max-w-[800px]
          space-y-4
        "
      >
        <StepGroup
          steps={turn.steps}
        />

        {turn.approvals.map(
          approval => (
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
          message => (
            <MessageView
              key={
                message.public_id
                || message.id
              }
              message={message}
            />
          )
        )}

        <TurnArtifacts
          artifacts={
            turn.artifacts
          }
        />
      </div>
    </section>
  );
}
```

---

# 33. Workbench 模块化

第一轮只移动代码，不改变行为：

```text
PreviewFrame
CodeEditor
ChangesList
TestsTab
ArtifactsList
ConsoleLogs
```

从 `PreviewPanel.tsx` 拆出去。

第二轮再抽：

```text
useWorkspaceTree
useEditorTabs
usePreviewRuntime
useRevisionDiff
```

这能明显降低后续 UI 修改成本。

---

# 34. Parser / Capability V2

长期应该从：

```text
truncate at 32 chunks
```

改为：

```text
All chunks
→ map summaries
→ group reduce
→ intermediate reduce
→ final reduce
```

预算限制通过：

```text
summary compression
```

解决，而不是丢后半篇。

最终输出：

```text
CapabilityCard
CapabilityContract
ParseCoverage
```

Planner 消费 Contract。

---

# 35. Event Runtime 最终形态

```text
EventEmitter
↓
EventStore.append()
↓
EventBroker.publish()
↓
SSE
```

当前 EventManager 同时负责 store/broker/cache 的多重职责应拆开。

单机：

```text
SQLiteEventStore
InProcessBroker
```

Production：

```text
SQLite/Postgres EventStore
RedisBroker
```

业务层无需变化。

---

# 36. Type Contract / Store

建议目录：

```text
web/lib/api/
  client.ts
  schema.d.ts
  types.ts

web/lib/realtime/
  run-stream.ts
  events.ts
  reducer.ts
  stream-buffer.ts

web/lib/store/
  run-slice.ts
  conversation-slice.ts
  task-slice.ts
  workbench-slice.ts
  ui-slice.ts
```

API type 与 UI state 分离。

---

# 37. 关键测试矩阵

## Task ID 一致性

```python
@pytest.mark.asyncio
async def test_message_and_task_share_task_id(
    client,
    storage,
    run_id,
):
    response = await client.post(
        f"/api/runs/{run_id}/messages",
        json={
            "content": "hello",
            "mode": "queue",
        },
    )

    payload = response.json()

    task = storage.get_task(
        payload["task_id"]
    )

    assert (
        payload["message"][
            "task_id"
        ]
        == task["id"]
    )
```

## Assistant Task ID

```python
@pytest.mark.asyncio
async def test_assistant_messages_keep_task_id(
    storage,
    orchestrator,
    task,
):
    await orchestrator.run(
        run_id=task["run_id"],
        user_message=task["goal"],
        task_id=task["id"],
    )

    messages = (
        storage.list_messages(
            task["run_id"]
        )
    )

    assistant = [
        item
        for item in messages
        if item["role"]
           == "assistant"
    ]

    assert assistant

    assert all(
        item["task_id"]
        == task["id"]
        for item in assistant
    )
```

## Finish 不结束 Thread

```python
@pytest.mark.asyncio
async def test_finish_only_completes_task(
    storage,
    run,
    task,
):
    await run_task(task)

    assert (
        storage.get_task(
            task["id"]
        )["status"]
        == "completed"
    )

    assert (
        storage.get_run(
            run["id"]
        )["status"]
        != "done"
    )
```

## Exact Claim

```python
def test_claim_task_cannot_claim_other_run(
    storage,
):
    a = storage.create_task(
        run_id="run_a"
    )

    b = storage.create_task(
        run_id="run_b"
    )

    claimed = storage.claim_task(
        task_id=a["id"],
        worker_id="worker",
        lease_until=FUTURE,
    )

    assert claimed["id"] == a["id"]

    assert (
        storage.get_task(
            b["id"]
        )["status"]
        == "queued"
    )
```

## Generation V3 Wiring

```python
@pytest.mark.asyncio
async def test_generate_uses_v3_batches(
    monkeypatch,
    context,
):
    calls = {
        "plan": 0,
        "batch": 0,
    }

    async def fake_plan(
        *args,
        **kwargs,
    ):
        calls["plan"] += 1
        return PLAN

    async def fake_batch(
        *args,
        **kwargs,
    ):
        calls["batch"] += 1
        return BATCH

    monkeypatch.setattr(
        generation_v3,
        "plan_workspace",
        fake_plan,
    )

    monkeypatch.setattr(
        generation_v3,
        "generate_batch",
        fake_batch,
    )

    await handle_generate(
        {
            "prd_id": "prd_1"
        },
        context,
    )

    assert calls["plan"] == 1
    assert calls["batch"] > 1
```

## Turn Projection

```typescript
it(
  "projects a complete task turn",
  () => {
    const turns =
      projectTurns(
        [task],
        [
          userMessage,
          assistantMessage,
        ],
        [step],
        [approval],
        [artifact],
      );

    expect(turns).toHaveLength(1);

    expect(
      turns[0].userMessage
        ?.task_id
    ).toBe(task.id);

    expect(
      turns[0]
        .assistantMessages
    ).toHaveLength(1);

    expect(
      turns[0].steps
    ).toHaveLength(1);

    expect(
      turns[0].approvals
    ).toHaveLength(1);

    expect(
      turns[0].artifacts
    ).toHaveLength(1);
  }
);
```

## Jump Button

```typescript
test(
  "jump button appears after manual scroll",
  async ({ page }) => {
    await seedLongConversation(
      page
    );

    const scroller =
      page.getByTestId(
        "conversation-scroll"
      );

    await scroller.evaluate(
      node => {
        node.scrollTop = 0;
      }
    );

    await expect(
      page.getByRole(
        "button",
        {
          name:
            /jump to latest/i,
        }
      )
    ).toBeVisible();
  }
);
```

---

# 38. 推荐 PR 顺序

## PR-A — Domain ID Correctness

```text
create_task(task_id=)
user message task_id
assistant task_id
tool message task_id
artifact.task_id
approval.task_id
event → entity task_id
```

## PR-B — Persistent Thread Closure

```text
finish = Task completion
Run 不再 done
remove run.done early return
Task lifecycle state machine
```

## PR-C — Scheduler Correctness

```text
claim_task(task_id)
queue 不保存 coroutine
startup recover queued tasks
per-run serialization
```

## PR-D — Generation V3 Wiring

```text
handle_generate → generation_v3
batch progress
batch revisions
删除 single giant JSON 主路径
```

## PR-E — Verification Authority

```text
technical_ready
preview_allowed
product_ready
成为唯一 readiness contract
```

## PR-F — Turn UI Closure

```text
完整 task entities
Jump state
删除 RunHeader
legacy untracked only
```

## PR-G — Workbench Split

```text
PreviewFrame
Editor
Changes
Tests
Artifacts
Logs
```

先纯 refactor。

## PR-H — Parser / Types / Broker / Preview Origin

最后处理 production 与长期质量。

---

# 39. 必须删除的旧路径

新路径接通后，应明确删除：

```text
Run.status = done
RunPhase.DONE 作为 thread terminal

Queue[
  tuple[
    task_id,
    Coroutine
  ]
]

claim_next_task()
用于“已经知道 task_id”的 per-run worker

handle_generate
→ old nextjs_generator giant JSON

ready_for_preview
作为 orchestration authority

ChatPanel.RunHeader
```

Turn 数据完整以后：

```text
untracked synthetic turn
```

只为 legacy 数据保留。

---

# 40. Definition of Done

## Continuous Agent

- [ ] Productize 完成后 Run 可以继续；
- [ ] 第二条修改请求不会被 `run.done` 拦截；
- [ ] 已有 workspace 时不重新 parse paper；
- [ ] inspect/read/patch/check 可连续执行；
- [ ] 每个 Task 独立完成。

## Task Integrity

- [ ] User Message.task_id == Task.id；
- [ ] Assistant Message.task_id == Task.id；
- [ ] Tool Message.task_id == Task.id；
- [ ] Step.task_id == Task.id；
- [ ] Artifact.task_id == Task.id；
- [ ] Approval.task_id == Task.id；
- [ ] Event.task_id == Task.id；
- [ ] reload 后 Turn 仍完全正确。

## Scheduler

- [ ] 同一 Run Task 串行；
- [ ] 不同 Run 不错 claim；
- [ ] restart 后 queued/stale task 可恢复；
- [ ] Queue 不依赖 coroutine；
- [ ] lease/reclaim 有 integration test。

## Generation

- [ ] 真正走 Generation V3；
- [ ] Plan 独立 call；
- [ ] 按 batch 生成；
- [ ] batch 可 retry；
- [ ] dependency-aware context；
- [ ] batch 有 step/revision/event。

## Verification

- [ ] Hard Gate 唯一权威；
- [ ] Security fail 不 product_ready；
- [ ] Typecheck fail 不 technical_ready；
- [ ] Build pass 可 preview；
- [ ] Acceptance fail 可 debug，但不 product_ready。

## UI

- [ ] 每 Task 是 Turn；
- [ ] Step/Approval/Artifact inline；
- [ ] Jump to latest 正常；
- [ ] 没有重复 RunHeader；
- [ ] Workbench adaptive 正常；
- [ ] PreviewPanel 已拆分；
- [ ] streaming 无需刷新。

## Parser / Production

- [ ] 长论文最终 whole-paper hierarchy；
- [ ] CapabilityContract 进入 Planner；
- [ ] Broker 可替换；
- [ ] Preview origin 可独立；
- [ ] OpenAPI types 真正成为 API contract。

---

# 41. 文件级修改清单

## `api/routes/messages.py`

```text
+ task_id 与 create_task 显式共享
+ 最好 transaction 创建 Message+Task
```

现有 queue/interrupt 逻辑保留。

## `paperforge/storage/db.py`

```text
+ create_task(task_id optional)
+ claim_task(task_id)
+ list_queued_tasks
+ artifact.task_id
+ approval.task_id
+ indexes
+ canonical schema 收敛
```

## `paperforge/orchestrator/loop.py`

```text
- run.done terminal
+ assistant streaming task_id
+ tool message task_id
+ final assistant task_id
+ Task completion != Run completion
```

Provider stream / Resource Gate 保留。

## `paperforge/orchestrator/tasks.py`

```text
- Queue coroutine
- global claim for known task
+ Queue task_id
+ reconstruct execution from DB
+ exact claim
+ startup recovery
```

## `paperforge/orchestrator/tools.py`

```text
+ Generation V3 entry
+ task-aware artifacts
- finish next_phase=done
- readiness based on ready_for_preview
```

Workspace tools 保留。

## `paperforge/agents/generation_v3.py`

```text
+ high-level generate_nextjs_app_v3()
+ scaffold/promotion
+ progress/revision callbacks
```

## `paperforge/agents/verifier.py`

保留：

```text
technical_ready
preview_allowed
product_ready
targeted repair
```

删除旧 readiness 业务权威。

## `web/lib/run-events.ts`

```text
+ task_id = data.task_id ?? event.task_id
```

建议把结果名：

```text
unknown
→ ignored
```

语义更准确。

## `web/lib/project-turns.ts`

结构保留。

修完后端后仅保留 legacy untracked fallback。

## `web/components/ChatPanel.tsx`

```text
+ useState(showJump)
- jumpRef.visible
- RunHeader
```

## `web/components/PreviewPanel.tsx`

拆分，不再继续堆新功能。

## `web/lib/api.ts`

逐步切换 generated OpenAPI types。

## `paperforge/agents/paper_parser.py`

ParseCoverage 保留。

下一阶段：

```text
truncation
→ hierarchical reduction
```

## `paperforge/orchestrator/events.py`

Task-aware emitter 保留。

Production：

```text
EventManager internal fanout
→ EventBroker
```

---

# 42. 最终判断

本轮基于 `main@0aa84cb` 重新审查后，可以确认：

```text
早期：
基础设施缺失

中期：
新架构逐步加入

现在：
绝大多数模块已经存在，
但关键 Domain Contract 与主链仍有断点
```

所以现在最重要的问题已经不再是：

```text
有没有 Streaming？
有没有 Workspace Tool？
有没有 Queue？
有没有 Turn UI？
有没有 Hard Gate？
```

这些基本都有。

现在应该问的是：

```text
这些东西是否真正属于同一个 Task？
finish 是否真的只结束当前 Task？
scheduler 是否不会错领 Task？
restart 后任务能否恢复？
Generation V3 是否真的运行？
Hard Gate 是否真的控制 orchestration？
reload 后 Turn 是否还能保持完整？
```

只有这些都成立后，才能说这一轮重构真正完整。

推荐最终推进顺序：

```text
PR-A Domain ID Correctness
↓
PR-B Persistent Thread
↓
PR-C Scheduler Correctness
↓
PR-D Generation V3 Wiring
↓
PR-E Verification Authority
↓
PR-F Turn UI Closure
↓
PR-G Workbench Split
↓
PR-H Parser / Broker / Types
```

A~F 收口之后，PaperForge 才会从：

> “已经拥有很多 Agent 产品组件”

真正变成：

> **“一个稳定、连续、可恢复、可修改、可验证的论文产品化 Agent Workspace。”**

---

# 审查依据

本文件以 GitHub 最新公开提交：

```text
0aa84cb
feat(sandbox): disable container network by default
```

作为稳定锚点。

重点逐行核对：

```text
api/routes/messages.py
api/main.py

paperforge/storage/db.py

paperforge/orchestrator/loop.py
paperforge/orchestrator/tools.py
paperforge/orchestrator/tasks.py
paperforge/orchestrator/workspace.py
paperforge/orchestrator/events.py
paperforge/orchestrator/stream_writer.py

paperforge/agents/generation_v3.py
paperforge/agents/nextjs_generator.py
paperforge/agents/verifier.py
paperforge/agents/browser_smoke.py
paperforge/agents/paper_parser.py

web/lib/project-turns.ts
web/lib/run-events.ts
web/lib/useRunSession.ts
web/lib/api.ts

web/components/Composer.tsx
web/components/ChatPanel.tsx
web/components/PreviewPanel.tsx

web/app/runs/[id]/page.tsx
```

仓库：

```text
https://github.com/Vincent-Wenhan/PaperForge
```
