# PaperForge 最新实现完整性复审与未完成项

> **复审日期：2026-08-13**  
> **仓库：** `Vincent-Wenhan/PaperForge`  
> **分支：** `main`  
> **锁定审查快照：** `0aa84cb`（当前 GitHub `main` 可验证的最新公开提交，History 显示 58 commits）  
> **审查方法：** 本轮不根据前几份方案推断“应该已经改了什么”，而是固定到 `0aa84cb`，直接读取该 commit 的 raw 源码，沿 `Message → Task → Orchestrator → Tool → Generation → Verification → Sandbox → SSE → Frontend Turn/Workbench` 主链重新核对。  
> **目标：** 判断哪些功能已经真正进入 production path，哪些只是存在 schema/helper/测试文件，哪些仍然存在会影响实际使用的集成 Bug。

---

# 0. 结论

**还没有完整实现。**

PaperForge 当前已经完成了大量基础重构，特别是：

```text
✓ StreamWriter 流式输出
✓ ProviderStreamEvent
✓ SSE v2 / replay / seq cursor
✓ 前端 rAF delta buffer
✓ Resource Gate 已进入 Orchestrator
✓ Workspace Tools
✓ SafeWorkspacePatch
✓ PRD V2
✓ Browser interaction executor
✓ Task / Step
✓ Queue / Interrupt 的 API/UI 骨架
✓ Turn Projection
✓ Adaptive Workbench
✓ Targeted Repair V2
✓ Verification hard-gate 字段
✓ Generation V3 的 planner / batch helper
✓ Worker lease 数据字段
✓ Sandbox hardening / network default-off
```

但是，**当前仓库最关键的问题不是“没有这些模块”，而是这些模块还没有完全组成一条正确的、连续的、可恢复的主链。**

这次锁定 `0aa84cb` 后确认仍存在以下核心未完成项：

```text
P0-1  User Message.task_id 与真正 Task.id 不一致
P0-2  Streaming Assistant / Tool / Final Assistant 的 task_id 没有完整持久化
P0-3  finish 仍将整个 Run 设为 done，下一轮 follow-up 被直接拦截
P0-4  Stop / Interrupt 仍将整个 Run 设为 cancelled，Continuous Agent 被破坏
P0-5  RunQueue 仍保存 Python coroutine，不是真正 durable scheduler
P0-6  RunQueue 使用全局 claim_next_task()，多 Run 时可能错领任务
P0-7  Startup 只 reconcile stale task，没有真正重新 enqueue / 执行
P0-8  Generation V3 只实现 helper，production handle_generate 仍走 V2 single-call generator
P0-9  Verification hard gates 已计算，但 Tool Handler 仍使用旧 ready_for_preview
P0-10 Preview runtime/acceptance 完成后没有统一 recompute product_ready

P1-1  Artifact / Approval 没有 durable task_id，Turn hydration 不完整
P1-2  Tool Resource Registry 不完整且 unknown tool fail-open
P1-3  EventBroker 只是 scaffold，EventManager 仍自管 subscriber
P1-4  Event persistence failure 会制造只存在于内存的 seq
P1-5  Task 列表 DESC，Conversation Turn 很可能 newest-first
P1-6  Jump-to-latest 使用 useRef，不会可靠触发 React rerender
P1-7  ChatPanel 仍有重复 RunHeader
P1-8  PreviewPanel 仍是 902 行 God Component
P1-9  Frontend Preview iframe 仍没有真正使用 server preview_url
P1-10 Verifier streaming checks 丢掉 process exit code
P1-11 Browser upload criterion 可读取任意本地路径
P1-12 Workspace identity 变化后旧 Editor Tabs 不清理
P1-13 API client 仍依赖 Store type / any，OpenAPI contract 没成为权威

P2-1  Parser 仍最多处理 32 chunks / 16 map chunks
P2-2  ParseCoverage 对失败 chunk 的 processed pages 计算可能错误
P2-3  CapabilityContract 仍是 schema-only，Planner 继续使用 CapabilityCard
P2-4  Multi-worker live SSE 仍未实现 shared broker
P2-5  当前所谓 full pipeline E2E 并没有真正执行完整产品化链路
```

因此当前 PaperForge 更准确的状态是：

> **模块完成度已经较高，但主链完整性、Task/Run 领域语义、Durable Scheduler、Generation V3 production wiring、Verification 闭环和 UI 数据归属仍未完成。**

---

# 1. 当前实现状态矩阵

| 模块 | 当前代码状态 | 主链状态 | 本轮结论 |
|---|---|---|---|
| StreamWriter | 已有 | 已接 | ✅ |
| ProviderStreamEvent | 已有 | 已接 | ✅ |
| SSE envelope/replay | 已有 | 已接 | ✅ |
| rAF stream buffer | 已有 | 已接 | ✅ |
| Resource Gate | 已有 | 已接 | ✅，registry 不完整 |
| Workspace restore | 已有 | 已接 | ✅ |
| Workspace inspect/read/patch/check | 已有 | 已接 | ✅ |
| PRD V2 | 已有 | 已接 | ✅ |
| Browser click/fill/select/upload | 已有 | 已接 | ✅，upload 有安全问题 |
| Task table | 已有 | 已接 | ⚠️ ID contract 有 Bug |
| Steps | 已有 | 已接 | ✅ |
| Queue/Interrupt | 已有 | 已接 | ⚠️ scheduler 不 durable |
| Turn Projection | 已有 | 已接 | ⚠️ task attribution 不完整 |
| Generation V3 | helper 已有 | **未接** | ❌ |
| Generation V2 | 已有 | **production 主路径** | ⚠️ monolithic |
| Verification hard gates | 已有 | 部分接 | ⚠️ 旧 readiness 仍掌权 |
| Runtime acceptance | 已有 | 已接 | ⚠️ product_ready 不闭环 |
| Worker lease | storage 已有 | 部分接 | ⚠️ |
| Restart recovery | reconcile 有 | executor recovery 无 | ❌ |
| EventBroker | interface 有 | 未接 | ❌ |
| Adaptive Workbench | 已有 | 已接 | ✅ |
| PreviewPanel 拆分 | 未完成 | 902 行 | ❌ |
| Whole-paper parser | 未实现 | bounded partial | ❌ |
| CapabilityContract runtime | schema 有 | 未接 | ❌ |
| OpenAPI authoritative types | 部分有 | 未接 | ⚠️ |

---

# 2. 已经真正实现的部分

先明确哪些**不应该继续重复重构**。

## 2.1 Streaming 主链已经基本正确

当前 Orchestrator 已经：

```python
stream_events = getattr(
    self.llm,
    "stream_events",
    None,
)
```

并统一消费：

```text
text_delta
tool_done
done
```

同时使用：

```python
StreamWriter(
    run_id=run_id,
    message_id=message_id,
    storage=self.storage,
    emit=emit,
)
```

因此已经不是早期：

```text
每个 provider chunk
→ 同步 SQLite
→ React rerender
```

那套结构。

前端 `run-events.ts` 也已经通过：

```typescript
enqueueMessageDelta(...)
flushMessageDeltas()
```

做浏览器帧级 batching。

### 结论

```text
Backend streaming architecture   已实现
Provider-neutral stream          已实现
SSE transport                    已实现
frontend delta batching          已实现
```

后续主要修的是：

```text
task_id attribution
UI rerender / scroll
```

而不是再重写 streaming protocol。

---

# 3. P0-1：User Message 的 task_id 与真正 Task.id 不一致

这是当前最明确的 Domain Bug 之一。

## 3.1 当前 Message API

`api/routes/messages.py`：

```python
task_id = (
    f"task_"
    f"{_uuid.uuid4().hex}"
)

message = storage.add_message(
    run_id=run_id,
    role="user",
    content=req.content,
    public_id=req.public_id,
    task_id=task_id,
)

task = storage.create_task(
    run_id=run_id,
    title=...,
    goal=req.content,
    status="queued",
    phase=...,
    priority=...,
    user_message_id=message["id"],
)
```

代码看起来像：

```text
先生成 Task ID
→ User Message 绑定
→ 创建 Task
```

但 Storage 当前：

```python
def create_task(
    self,
    run_id: str,
    ...,
) -> dict[str, Any]:
    task_id = (
        f"task_"
        f"{uuid.uuid4().hex}"
    )
```

会再生成一个新的 ID。

于是实际：

```text
User Message.task_id
=
task_A

Task.id
=
task_B
```

## 3.2 直接影响 Turn Projection

前端：

```typescript
const messageByTask =
  groupByTask(
    messages,
    taskIdOf
  );

for (
  const task
  of tasks
) {
  const id =
    task.id
    ?? task.task_id
    ?? "";

  const taskMessages =
    messageByTask.get(id)
    || [];
}
```

因此 User Message 会落到：

```text
"untracked"
```

而真正 Task Turn：

```text
userMessage = null
```

这会直接破坏：

```text
User Turn
  └ Assistant / Steps
```

的 UI 结构。

---

# 4. Task ID 正确修复

## 4.1 Storage 接收显式 task_id

```python
def create_task(
    self,
    run_id: str,
    title: str | None = None,
    goal: str | None = None,
    status: str = "queued",
    phase: str = "init",
    priority: int = 0,
    user_message_id:
        int | None = None,
    task_id:
        str | None = None,
) -> dict[str, Any]:

    now = (
        datetime.utcnow()
        .isoformat()
    )

    task_id = (
        task_id
        or (
            f"task_"
            f"{uuid.uuid4().hex}"
        )
    )

    with (
        self._lock,
        self._conn() as conn
    ):
        conn.execute(
            """
            INSERT INTO tasks (
                id,
                run_id,
                title,
                goal,
                status,
                phase,
                priority,
                user_message_id,
                created_at,
                updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
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

    return self.get_task(
        task_id
    )
```

## 4.2 API 使用同一个 ID

```python
task_id = (
    f"task_"
    f"{_uuid.uuid4().hex}"
)

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
    title=(
        req.content.strip()[:120]
        or "Productization task"
    ),
    goal=req.content,
    status="queued",
    phase=(
        storage
        .get_run_phase(run_id)
    ),
    priority=(
        100
        if req.mode == "interrupt"
        else 0
    ),
    user_message_id=message["id"],
)
```

---

# 5. 更进一步：Message + Task 应在一个 Transaction 里创建

当前顺序仍可能：

```text
Message INSERT 成功
Task INSERT 失败
```

于是数据库留下：

```text
message.task_id
指向不存在 Task
```

推荐：

```python
@dataclass(frozen=True)
class CreatedUserTask:
    task: dict[str, Any]
    message: dict[str, Any]


def create_user_task(
    self,
    *,
    run_id: str,
    content: str,
    public_id:
        str | None,
    priority: int,
    phase: str,
) -> CreatedUserTask:

    task_id = (
        f"task_"
        f"{uuid.uuid4().hex}"
    )

    now = (
        datetime.utcnow()
        .isoformat()
    )

    with (
        self._lock,
        self._conn() as conn
    ):
        conn.execute(
            "BEGIN IMMEDIATE"
        )

        try:
            cur = conn.execute(
                """
                INSERT INTO messages (
                    public_id,
                    run_id,
                    role,
                    content,
                    status,
                    task_id,
                    created_at
                )
                VALUES (
                    ?, ?, 'user',
                    ?, 'completed',
                    ?, ?
                )
                """,
                (
                    public_id,
                    run_id,
                    content,
                    task_id,
                    now,
                ),
            )

            message_id = (
                cur.lastrowid
            )

            conn.execute(
                """
                INSERT INTO tasks (
                    id,
                    run_id,
                    title,
                    goal,
                    status,
                    phase,
                    priority,
                    user_message_id,
                    created_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?,
                    'queued',
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    task_id,
                    run_id,
                    content[:120],
                    content,
                    phase,
                    priority,
                    message_id,
                    now,
                    now,
                ),
            )

            conn.execute(
                "COMMIT"
            )

        except Exception:
            conn.execute(
                "ROLLBACK"
            )
            raise

    return CreatedUserTask(
        task=self.get_task(
            task_id
        ),
        message=self.get_message(
            message_id
        ),
    )
```

---

# 6. P0-2：Assistant / Tool Message 的 task_id 仍然没有完整持久化

即使修好 User Message，当前 Turn 仍不会完整。

## 6.1 Streaming Assistant

当前 Storage：

```python
def create_streaming_message(
    self,
    run_id: str,
    public_id: str,
) -> dict[str, Any]:

    return self.add_message(
        run_id=run_id,
        role="assistant",
        content="",
        public_id=public_id,
        status="streaming",
    )
```

没有：

```text
task_id
```

Orchestrator：

```python
self.storage
    .create_streaming_message(
        run_id,
        message_id,
    )
```

也没有传。

因此 Streaming Assistant durable row：

```text
task_id = NULL
```

刷新页面后就会进入：

```text
untracked
```

---

# 7. Assistant task_id 修复

```python
def create_streaming_message(
    self,
    run_id: str,
    public_id: str,
    *,
    task_id:
        str | None = None,
) -> dict[str, Any]:

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
self.storage
    .create_streaming_message(
        run_id,
        message_id,
        task_id=self.task_id,
    )
```

---

# 8. Tool Message 同样缺 task_id

当前：

```python
self.storage.add_message(
    run_id=run_id,
    role="tool",
    content=result_str,
    tool_call_id=call.id,
    name=call.name,
)
```

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

---

# 9. Final Assistant 无 streaming ID 时也缺 task_id

当前：

```python
if not response.message_id:
    self.storage.add_message(
        run_id=run_id,
        role="assistant",
        content=final_content,
    )
```

修：

```python
if not response.message_id:
    self.storage.add_message(
        run_id=run_id,
        role="assistant",
        content=final_content,
        task_id=self.task_id,
    )
```

---

# 10. Frontend `message.started` 也应该保存 event.task_id

当前：

```typescript
case "message.started":
  store.upsertMessage({
    id: data.message_id,
    public_id: data.message_id,
    role: "assistant",
    content: "",
    streaming: true,
    status: "streaming",
  });
```

SSE envelope 本身已经有：

```text
event.task_id
```

应该：

```typescript
case "message.started":
  store.upsertMessage({
    id:
      data.message_id,

    public_id:
      data.message_id,

    task_id:
      data.task_id
      ?? event.task_id
      ?? undefined,

    role:
      "assistant",

    content:
      "",

    streaming:
      true,

    status:
      "streaming",
  });

  return "applied";
```

这样：

```text
realtime Turn
=
reload 后的 Turn
```

才一致。

---

# 11. P0-3：`finish` 仍然会结束整个 Persistent Run

代码注释已经说：

```text
Run = persistent thread
```

但运行时模型仍然是旧的：

```text
Run = one pipeline
```

这是当前 Continuous Agent 最大冲突之一。

## 11.1 RunPhase 仍然有 DONE

```python
class RunPhase(
    str,
    Enum,
):
    ...
    PREVIEW_READY = (
        "preview_ready"
    )
    DONE = "done"
    ERROR = "error"
```

---

# 12. Main Loop 仍然把 DONE 映射成 Run.done

```python
terminal_status = (
    "done"
    if (
        self.phase
        == RunPhase.DONE
    )
    else ...
)
```

随后：

```python
self.storage
    .update_run_status(
        run_id,
        terminal_status,
    )
```

Task 同时：

```python
status="completed"
if terminal_status
   == "done"
```

所以：

```text
Task completed
→ Run completed
```

仍然绑定在一起。

---

# 13. 下一轮 Orchestrator 会直接拒绝 done Run

Orchestrator 开头：

```python
prev_status = (
    self.storage
    .get_run_status(run_id)
    or "active"
)

if prev_status in {
    "cancelled",
    "done",
}:
    return
```

因此：

```text
第一次：
Productize paper
↓
finish
↓
Run.done

第二次：
Make the sidebar narrower
↓
Message API 成功创建 Task
↓
Queue 调 Orchestrator
↓
Orchestrator 看见 Run.done
↓
return
```

这意味着：

> **“生成完 App 以后继续像 Codex 一样修改”在当前 commit 仍没有真正完成。**

---

# 14. 最终领域模型必须改成

```text
Run / Thread
=
持久 conversation + workspace

Task
=
一次 user request
```

状态：

```text
Run:
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

核心：

```text
Task.completed
≠
Run.done
```

---

# 15. `finish` 正确语义

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
        status=(
            ToolStatus.SUCCEEDED
        ),
        data={
            "summary":
                summary,
            "task_status":
                "completed",
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
        is not None
        and stopped_result.code
            == "needs_user_input"
    )

    if waiting_for_user:
        task_status = (
            "waiting_user"
        )
        run_status = (
            "waiting_user"
        )
    else:
        task_status = (
            "completed"
        )
        run_status = (
            "active"
        )

    self._update_task(
        status=task_status,
        phase=self.phase.value,
    )

    previous = (
        self.storage
        .get_run_status(run_id)
        or "running"
    )

    self.storage
        .update_run_status(
            run_id,
            run_status,
        )

    await emit.run_status_changed(
        run_status,
        previous,
    )

    await emit.run_updated(
        status=run_status,
        phase=self.phase.value,
    )

    await emit.run_finished()

    return
```

长期应删除：

```text
RunPhase.DONE
Run.status = done
```

作为 Thread terminal。

真正 terminal：

```text
archived_at
deleted
```

---

# 16. P0-4：Stop / Interrupt 仍然会毒死整个 Thread

当前 Interrupt：

```python
if req.mode == "interrupt":
    await (
        _run_queue
        .cancel_and_wait(
            run_id
        )
    )
```

这本身是合理的：

```text
cancel Task A
→ start Task B
```

但是被 cancel 的 Orchestrator：

```python
except asyncio.CancelledError:
    self.storage
        .update_run_status(
            run_id,
            "cancelled",
        )

    self._update_task(
        status="cancelled",
        phase=self.phase.value,
    )

    raise
```

于是：

```text
Task A cancelled
↓
Run.cancelled
```

然后新 Task B：

```text
queue
↓
Orchestrator.run()
↓
prev_status == cancelled
↓
return
```

所以 Interrupt 在当前领域模型中是断的。

---

# 17. Stop API 同样是旧语义

当前：

```text
POST /runs/{run_id}/cancel
```

最终：

```python
storage.update_run_status(
    run_id,
    "cancelled",
)
```

这实际上是：

```text
Cancel Thread
```

但产品按钮语义通常是：

```text
Stop current task
```

这两者必须统一。

---

# 18. 正确 Cancellation 设计

应该：

```text
Task.cancel
=
停止当前任务

Run.archive
=
终止 Thread 的继续使用
```

CancelledError：

```python
except asyncio.CancelledError:
    previous = (
        self.storage
        .get_run_status(run_id)
        or "running"
    )

    self._update_task(
        status="cancelled",
        phase=self.phase.value,
    )

    # Persistent thread
    # remains available.
    self.storage
        .update_run_status(
            run_id,
            "active",
        )

    with contextlib.suppress(
        Exception
    ):
        await (
            emit
            .run_status_changed(
                "active",
                previous,
            )
        )

        await emit.run_updated(
            status="active",
            phase=self.phase.value,
        )

    raise
```

Orchestrator 开头不要：

```python
if prev_status
   in {"cancelled", "done"}:
    return
```

只应该检查：

```python
if (
    run_row
    and run_row.get(
        "archived_at"
    )
):
    return
```

---

# 19. 推荐 Task-level Cancel Endpoint

```python
@router.post(
    "/{run_id}/tasks/"
    "{task_id}/cancel"
)
async def cancel_task(
    run_id: str,
    task_id: str,
) -> dict:

    storage = (
        get_storage()
    )

    task = (
        storage
        .get_task(
            task_id
        )
    )

    if (
        not task
        or task["run_id"]
            != run_id
    ):
        raise HTTPException(
            404,
            "Task not found",
        )

    if task["status"] == "running":
        await (
            get_run_queue()
            .cancel_and_wait(
                run_id
            )
        )

    storage.update_task(
        task_id=task_id,
        status="cancelled",
    )

    storage.update_run_status(
        run_id,
        "active",
    )

    return {
        "status":
            "cancelled",
        "task_id":
            task_id,
        "run_id":
            run_id,
    }
```

旧：

```text
POST /runs/{id}/cancel
```

可以暂时兼容，但内部也应该变成：

```text
Cancel active Task
```

而不是永久取消 Run。


# 20. P0-5：当前 RunQueue 仍然不是真正 Durable Scheduler

虽然 Task table 已经有：

```text
lease_owner
lease_until
attempt
started_at
```

而且启动时也会：

```python
storage.reconcile_stale_tasks()
```

但真实 executor 仍然是：

```python
asyncio.Queue[
    tuple[
        task_id,
        Coroutine
    ]
]
```

也就是说，队列中真正要执行的工作：

```python
orchestrator.run(...)
```

仍然是一个 Python coroutine object。

---

# 21. 为什么这不 Durable

进程重启以后：

```text
SQLite:
Task.status = running

reconcile_stale_tasks()
↓
Task.status = queued
```

但是：

```text
原来 Queue 里的 coroutine
已经随着 Python process 消失
```

当前 FastAPI startup 只有：

```python
storage.reconcile_stale_tasks()
```

没有：

```text
list queued task
→ reconstruct Orchestrator
→ enqueue again
```

所以：

```text
Durable Task metadata
✓

Durable execution
✗
```

---

# 22. Queue 必须只保存 Task ID

目标：

```python
class RunQueue:
    def __init__(
        self,
        storage: Storage,
        orchestrator_factory,
    ) -> None:

        self.storage = storage

        self.orchestrator_factory = (
            orchestrator_factory
        )

        self._queues:
            dict[
                str,
                asyncio.Queue[str],
            ] = {}

        self._workers:
            dict[
                str,
                asyncio.Task,
            ] = {}

    async def enqueue(
        self,
        run_id: str,
        task_id: str,
    ) -> None:

        queue = (
            self._queues
            .setdefault(
                run_id,
                asyncio.Queue(),
            )
        )

        await queue.put(
            task_id
        )

        worker = (
            self._workers
            .get(run_id)
        )

        if (
            worker is None
            or worker.done()
        ):
            self._workers[
                run_id
            ] = (
                asyncio
                .create_task(
                    self._worker(
                        run_id
                    )
                )
            )
```

真正执行时：

```python
async def _execute_task(
    self,
    task_id: str,
) -> None:

    task = (
        self.storage
        .get_task(
            task_id
        )
    )

    if not task:
        return

    orchestrator = (
        self
        .orchestrator_factory()
    )

    await orchestrator.run(
        run_id=task["run_id"],
        user_message=(
            task.get("goal")
            or ""
        ),
        task_id=task["id"],
    )
```

这样 DB Task row 才是真正 source of truth。

---

# 23. P0-6：RunQueue 当前会跨 Run 错领 Task

这是当前 Scheduler 更严重的 correctness bug。

当前 per-run worker 已经知道：

```text
run_id
task_id
```

但 `_claim_and_run()` 却调用：

```python
claimed = (
    storage
    .claim_next_task(
        worker_id=worker_id,
        lease_until=...,
    )
)
```

当前 SQL：

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
priority
```

随后才：

```python
if (
    not claimed
    or claimed["id"]
        != task_id
):
    return False
```

但是这时候：

```text
错误 Task
已经 UPDATE status='running'
```

---

# 24. 跨 Run 错领示例

```text
Run A
queue:
Task A

Run B
queue:
Task B

Task B
比 A 更早创建
```

Run A worker：

```text
知道自己应该执行 A

调用 global claim_next_task
↓
数据库选择 B
↓
B.status = running
↓
返回 B

worker:
B.id != A.id
↓
return False
```

结果：

```text
Task B
数据库已经 running
但 Run A worker 不执行 B

Run B worker
以后又无法正常 claim B
```

这会形成：

```text
orphan running task
```

---

# 25. 当前 Priority 也没有真正进入 Claim

Storage 的：

```python
get_next_queued_task(
    run_id
)
```

确实：

```sql
ORDER BY
    priority DESC,
    created_at ASC
```

但真正 `_claim_and_run()` 使用的是：

```text
claim_next_task()
```

它只：

```sql
ORDER BY
    created_at ASC
```

所以 Interrupt Task：

```text
priority = 100
```

在真实 claim 层也没有成为权威。

---

# 26. 正确实现 Exact Claim

当前 per-run Queue 模型下，最简单正确方案：

```python
def claim_task(
    self,
    *,
    task_id: str,
    worker_id: str,
    lease_until: str,
) -> dict[str, Any] | None:

    with (
        self._lock,
        self._conn() as conn
    ):
        conn.execute(
            "BEGIN IMMEDIATE"
        )

        try:
            row = conn.execute(
                """
                SELECT *
                FROM tasks
                WHERE id = ?
                  AND status = 'queued'
                """,
                (
                    task_id,
                ),
            ).fetchone()

            if not row:
                conn.execute(
                    "COMMIT"
                )
                return None

            cur = conn.execute(
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

            if cur.rowcount != 1:
                conn.execute(
                    "ROLLBACK"
                )
                return None

            conn.execute(
                "COMMIT"
            )

        except Exception:
            conn.execute(
                "ROLLBACK"
            )
            raise

    return self.get_task(
        task_id
    )
```

Worker：

```python
claimed = (
    storage.claim_task(
        task_id=task_id,
        worker_id=worker_id,
        lease_until=(
            lease_until
            .isoformat()
        ),
    )
)
```

---

# 27. Claim 失败不能盲目 Requeue

当前 worker：

```python
if not executed:
    storage.update_task(
        task_id=task_id,
        status="queued",
    )
```

这在未来多 worker 时同样危险。

场景：

```text
Worker A
claim 成功
Task = running

Worker B
也拿到同一个 task_id
claim 失败

B:
status = queued
```

于是：

```text
A 正在执行的 Task
被 B 重新写回 queued
```

另一个 worker 又可能 claim。

正确：

```python
if not executed:
    row = storage.get_task(
        task_id
    )

    if not row:
        continue

    status = (
        row.get("status")
    )

    if status == "queued":
        # still runnable
        ...

    elif status == "running":
        # another worker owns it
        pass

    elif status in {
        "completed",
        "failed",
        "cancelled",
    }:
        pass
```

更推荐 typed outcome：

```python
class ClaimOutcome(
    str,
    Enum,
):
    EXECUTED = "executed"

    OWNED_BY_OTHER = (
        "owned_by_other"
    )

    TERMINAL = (
        "terminal"
    )

    NOT_FOUND = (
        "not_found"
    )
```

---

# 28. P0-7：Startup Recovery 当前只“改状态”，不恢复执行

当前 FastAPI lifespan：

```python
storage
    .reconcile_stale_tasks()
```

这只能做到：

```text
expired running
→ queued
```

但没有：

```text
queued
→ actual scheduler
→ Orchestrator
```

所以 server restart 后：

```text
UI 不再显示 running
```

不等于：

```text
任务恢复执行
```

---

# 29. Startup 正确 Recovery

新增：

```python
def list_queued_tasks(
    self,
) -> list[
    dict[str, Any]
]:
    with self._conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM tasks
            WHERE status = 'queued'
            ORDER BY
                priority DESC,
                created_at ASC
            """
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]
```

Startup：

```python
storage.reconcile_stale_tasks()

scheduler = (
    get_run_queue()
)

for task in (
    storage.list_queued_tasks()
):
    await scheduler.enqueue(
        task["run_id"],
        task["id"],
    )
```

但这要求前面先完成：

```text
Queue 不保存 coroutine
```

否则重启时根本无法重建执行。

---

# 30. RunTaskManager 还有 Replacement Callback Race

当前：

```python
task = (
    asyncio
    .create_task(
        coro
    )
)

self.tasks[
    run_id
] = task

task.add_done_callback(
    lambda _:
        self.tasks.pop(
            run_id,
            None
        )
)
```

竞态：

```text
A 正在运行

start B
↓
A.cancel()

self.tasks[run] = B

A callback 稍后执行
↓
pop(run)
↓
B 从 manager 消失
```

此时：

```text
B 实际运行
is_running() 却 false
```

---

# 31. Callback 必须检查 identity

```python
def start(
    self,
    run_id: str,
    coro: Coroutine,
) -> asyncio.Task:

    existing = (
        self.tasks
        .get(run_id)
    )

    if (
        existing
        and not existing.done()
    ):
        existing.cancel()

    task = (
        asyncio
        .create_task(
            coro
        )
    )

    self.tasks[
        run_id
    ] = task

    def cleanup(
        done: asyncio.Task,
    ) -> None:

        if (
            self.tasks
            .get(run_id)
            is done
        ):
            self.tasks.pop(
                run_id,
                None
            )

    task.add_done_callback(
        cleanup
    )

    return task
```

---

# 32. Queue Worker 还有 Empty Queue Race

当前 worker：

```python
while (
    queue is not None
    and not queue.empty()
):
    task = await queue.get()
    ...
finally:
    self._queues.pop(
        run_id,
        None
    )
```

存在窗口：

```text
Worker:
queue.empty() == True

此时新 Task enqueue
↓
enqueue 看到旧 worker
还没有 done
↓
不创建新 worker

旧 worker finally
↓
pop queue

新 Task 留在
已经被 pop 的 queue object
```

Task DB 仍：

```text
queued
```

但当前进程没有 worker 会执行。

---

# 33. Scheduler 最终建议

如果项目准备长期维护，与其不断给 in-memory RunQueue 补竞态，建议最终变成：

```text
DB Task Queue
+
Worker
+
per-run serialization
```

数据库选择 runnable Task：

```sql
SELECT t.*
FROM tasks t
WHERE t.status = 'queued'

  AND NOT EXISTS (
      SELECT 1
      FROM tasks active
      WHERE
          active.run_id
              = t.run_id
      AND active.status
          = 'running'
  )

ORDER BY
    t.priority DESC,
    t.created_at ASC

LIMIT 1;
```

然后 transaction claim。

这样：

```text
DB
=
唯一 queue source of truth
```

Python 不再维护：

```text
业务级 Queue state
```

只负责执行 claim 到的 Task。

---

# 34. Worker Lease 也还没有真正形成互斥

当前 heartbeat：

```python
ok = (
    storage
    .renew_task_lease(...)
)

if not ok:
    return
```

如果失去 lease：

```text
heartbeat 停止
```

但真正的：

```text
Orchestrator coroutine
```

继续运行。

未来多 worker：

```text
Worker A lease lost
↓
A 继续 patch workspace

Worker B reclaim
↓
B 也开始 patch
```

所以可能：

```text
duplicate / concurrent execution
```

---

# 35. Lease Lost 必须 Cancel Execution

```python
lease_lost = (
    asyncio.Event()
)

heartbeat = (
    asyncio.create_task(
        self._heartbeat(
            ...,
            lease_lost=(
                lease_lost
            ),
        )
    )
)

run_task = (
    self._manager
    .start(
        run_id,
        coro,
    )
)

lease_waiter = (
    asyncio.create_task(
        lease_lost.wait()
    )
)

done, _ = (
    await asyncio.wait(
        {
            run_task,
            lease_waiter,
        },
        return_when=(
            asyncio
            .FIRST_COMPLETED
        ),
    )
)

if (
    lease_waiter in done
    and lease_lost.is_set()
):
    run_task.cancel()

    with contextlib.suppress(
        asyncio.CancelledError
    ):
        await run_task

    raise RuntimeError(
        "Task lease lost"
    )
```

---

# 36. Queue 不应该“猜测” Task 成功

当前：

```python
row = (
    storage
    .get_task(
        task_id
    )
)

status = (
    row["status"]
    if row
    else "failed"
)

if status == "running":
    storage.update_task(
        task_id=task_id,
        status="completed",
    )
```

也就是：

> Orchestrator 只要 return，而 Task 仍是 running，就自动算 completed。

这会掩盖很多错误：

```text
Run.done early return
Run.cancelled early return
future guard return
Bug 导致的 silent return
```

正确：

```text
Orchestrator
必须显式结束 Task

Scheduler
不能推断业务状态
```

如果 executor return 以后还：

```text
status == running
```

应该：

```python
storage.update_task(
    task_id=task_id,
    status="failed",
)

logger.error(
    "Task exited without "
    "terminal outcome"
)
```

而不是 completed。

---

# 37. P0-8：Generation V3 目前没有进入 Production Path

这是本轮最需要纠正的一个状态判断。

仓库确实已经有：

```text
paperforge/agents/
generation_v3.py
```

而且实现了：

```text
plan_workspace()
group_plan_files()
build_generation_context()
generate_batch()
write_batch_files()
```

也就是说：

```text
V3 architecture helper
✓
```

但是实际：

```python
handle_generate()
```

仍然：

```python
from (
    paperforge.agents
    .nextjs_generator
) import (
    generate_nextjs_app
)
```

然后：

```python
manifest = await (
    generate_nextjs_app(
        ...
    )
)
```

因此：

```text
Production Generator
=
Generation V2
```

---

# 38. 当前 V2 仍是 One Giant JSON

当前 `nextjs_generator.py` 的设计仍然是：

```text
PRD
↓
一次 LLM call
↓
{
  plan,
  files: [
    file1,
    file2,
    ...
  ]
}
↓
validate
↓
write all
```

所以虽然早期：

```text
3-file hard limit
```

已经被删除，但仍然存在：

```text
单一超大响应
JSON 截断风险
单文件错误导致整个 generation retry
无法按 dependency 精确提供 context
无法 batch retry
```

---

# 39. Generation V3 正确 High-Level Entry

当前缺的不是 helper，而是：

```text
generate_nextjs_app_v3()
```

真正 orchestration。

```python
async def generate_nextjs_app_v3(
    *,
    prd_id: str,
    output_dir:
        str | Path,
    llm: LLMClient,
    storage: Storage,
    progress=None,
) -> dict[str, Any]:

    prd_artifact = (
        storage
        .get_artifact(
            prd_id
        )
    )

    if not prd_artifact:
        raise ValueError(
            "PRD not found"
        )

    prd = (
        prd_artifact
        .get("data")
        or {}
    )

    output_dir = (
        Path(output_dir)
        .resolve()
    )

    temp_dir = (
        create_scaffold_temp(
            output_dir
        )
    )

    try:
        plan = (
            await plan_workspace(
                prd=prd,
                llm=llm,
            )
        )

        generated_files = []

        for (
            kind,
            specs
        ) in group_plan_files(
            plan
        ):

            step_id = None

            if progress:
                step_id = (
                    await progress.start(
                        kind="codegen",
                        title=(
                            "Generating "
                            f"{kind}"
                        ),
                    )
                )

            batch = (
                await generate_batch(
                    prd=prd,
                    plan=plan,
                    specs=specs,
                    workspace=(
                        temp_dir
                    ),
                    llm=llm,
                )
            )

            batch = (
                validate_generation_batch(
                    specs,
                    batch,
                )
            )

            changed = (
                write_batch_files(
                    workspace=(
                        temp_dir
                    ),
                    batch=batch,
                    policy=(
                        SafeWorkspacePolicy()
                    ),
                )
            )

            generated_files.extend(
                changed
            )

            if progress:
                await (
                    progress
                    .complete(
                        step_id,
                        summary=(
                            f"{len(changed)} "
                            "files generated"
                        ),
                    )
                )

        merge_dependencies(
            temp_dir,
            plan.dependencies,
        )

        validate_workspace(
            temp_dir,
            plan,
        )

        atomic_promote(
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
        "app_id":
            f"app_"
            f"{uuid.uuid4().hex}",

        "plan":
            plan.model_dump(),

        "files":
            generated_files,

        "output_dir":
            str(output_dir),
    }
```

---

# 40. `handle_generate()` 必须切 V3

```python
async def handle_generate(
    args: dict[str, Any],
    ctx: ToolContext,
) -> ToolResult:

    from (
        paperforge.agents
        .generation_v3
    ) import (
        generate_nextjs_app_v3
    )

    ...

    manifest = (
        await (
            generate_nextjs_app_v3(
                prd_id=prd_id,
                output_dir=(
                    output_dir
                ),
                llm=ctx.llm,
                storage=ctx.storage,
                progress=(
                    ctx.progress()
                ),
            )
        )
    )
```

V3 稳定后，旧 V2 不应该继续作为 production fallback，除非明确加：

```text
GENERATOR_MODE=v2|v3
```

用于 rollback。

否则两套 generator 长期并存会再次产生：

```text
“新功能写了但主路径没用”
```

的问题。

---

# 41. V3 当前 Batch Contract 也还不完整

即使接入 V3，当前 `generate_batch()` 只是：

```python
data = json.loads(...)

return {
    "summary":
        data.get(
            "summary",
            "",
        ),
    "files":
        data.get(
            "files",
            [],
        ),
}
```

没有 Pydantic output schema。

也没有检查：

```text
实际生成 files
==
WorkspacePlan 要求的 files
```

---

# 42. 必须增加 GeneratedBatch Schema

```python
class GeneratedFile(
    BaseModel
):
    path: str
    content: str


class GeneratedBatch(
    BaseModel
):
    summary: str = ""

    files: list[
        GeneratedFile
    ] = Field(
        min_length=1,
        max_length=32,
    )
```

验证：

```python
def validate_generation_batch(
    specs: list[FileSpec],
    batch: GeneratedBatch,
) -> None:

    expected = {
        spec.path
        for spec in specs
    }

    actual = {
        file.path
        for file
        in batch.files
    }

    if actual != expected:
        raise ValueError(
            "Generated batch "
            "does not match plan. "
            f"expected={expected}, "
            f"actual={actual}"
        )

    if (
        len(actual)
        != len(batch.files)
    ):
        raise ValueError(
            "Duplicate generated "
            "file paths"
        )
```

---

# 43. V3 写文件也必须走 SafeWorkspacePolicy

当前 `write_batch_files()` 只检查：

```text
resolve() 后没有逃出 workspace
```

但初始生成也应该和 Agent Patch 一样遵守：

```text
allowed roots
protected files
max file bytes
max total bytes
```

不能：

```text
apply_workspace_patch
很严格

initial generation
很宽松
```

统一：

```python
def write_batch_files(
    *,
    workspace: Path,
    batch: GeneratedBatch,
    policy:
        SafeWorkspacePolicy,
) -> list[str]:

    changed = []

    total_bytes = sum(
        len(
            file.content.encode(
                "utf-8"
            )
        )
        for file in batch.files
    )

    if (
        total_bytes
        > policy.MAX_PATCH_BYTES
    ):
        raise ValueError(
            "Generation batch "
            "too large"
        )

    for file in batch.files:
        relative = (
            policy.normalize(
                file.path
            )
        )

        policy.validate_content(
            file.content
        )

        target = (
            workspace
            / relative
        ).resolve()

        target.relative_to(
            workspace.resolve()
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_text(
            file.content,
            encoding="utf-8",
        )

        changed.append(
            relative
        )

    return changed
```

---

# 44. P0-9：Verification Hard Gates 已实现，但 Tool Handler 仍使用旧字段

Verifier 当前已经算：

```python
gates = {
    "workspace_ok":
        ...,
    "typecheck_ok":
        ...,
    "build_ok":
        ...,
    "lint_ok":
        ...,
    "security_ok":
        ...,
    "runtime_ok":
        None,
    "acceptance_ok":
        ...,
}

technical_ready = ...

preview_allowed = ...

product_ready = ...
```

这部分是对的。

但 `handle_verify()`：

```python
ready = bool(
    report.get(
        "ready_for_preview"
    )
)
```

然后：

```python
status = (
    ToolStatus.SUCCEEDED
    if ready
    else ToolStatus.FAILED
)
```

仍然用旧：

```text
ready_for_preview
```

做 orchestration authority。

---

# 45. 旧 `ready_for_preview` 仍是 Score-based

Verifier：

```python
ready_for_preview = (
    build_succeeded
    and score >= 0.6
    and not type_errors
)
```

这意味着：

```text
security_ok = False
```

不一定能直接阻止旧 ready 字段。

所以目前：

```text
Hard Gate 数据
✓

Hard Gate 作为 Agent 权威
✗
```

---

# 46. Verification Tool 的正确语义

Verifier 成功运行并发现：

```text
代码有错误
```

不应该代表：

```text
verify_app tool 自己 failed
```

它应该：

```text
Tool execution = succeeded
Product technical gate = false
```

例如：

```python
technical_ready = bool(
    report.get(
        "technical_ready"
    )
)

preview_allowed = bool(
    report.get(
        "preview_allowed"
    )
)

product_ready = bool(
    report.get(
        "product_ready"
    )
)

return ToolResult(
    tool="verify_app",

    status=(
        ToolStatus.SUCCEEDED
    ),

    artifact_id=artifact_id,

    data={
        "report":
            report,

        "technical_ready":
            technical_ready,

        "preview_allowed":
            preview_allowed,

        "product_ready":
            product_ready,
    },

    summary=(
        "Verification complete. "
        f"technical_ready="
        f"{technical_ready}; "
        f"product_ready="
        f"{product_ready}."
    ),

    next_phase=(
        "verified"
        if technical_ready
        else None
    ),
)
```

这样 Agent 才能：

```text
verify
→ technical_ready false
→ inspect report
→ repair
→ verify again
```

而不是把 verifier 运行本身当异常。

---

# 47. P0-10：Runtime 完成后 `product_ready` 没有完整闭环

初始 Verification：

```text
runtime_ok = None
```

所以：

```text
product_ready = False
```

这是正确的，因为 Sandbox 还没真正启动。

随后：

```text
run_in_sandbox
→ preview ready
→ browser smoke
```

会更新 runtime/acceptance layer。

但当前代码没有统一更新：

```text
gates.runtime_ok
gates.acceptance_ok
technical_ready
preview_allowed
product_ready
```

因此正常完整 pipeline 可能：

```text
Build        Passed
Runtime      Passed
Acceptance   Passed

product_ready
False
```

---

# 48. Readiness 必须只有一个函数

```python
def recompute_readiness(
    report: dict[str, Any],
) -> dict[str, Any]:

    gates = report.setdefault(
        "gates",
        {},
    )

    technical_ready = all(
        gates.get(key)
        is True
        for key in (
            "workspace_ok",
            "typecheck_ok",
            "build_ok",
            "security_ok",
        )
    )

    preview_allowed = (
        gates.get(
            "workspace_ok"
        ) is True
        and gates.get(
            "build_ok"
        ) is True
    )

    product_ready = (
        technical_ready
        and gates.get(
            "runtime_ok"
        ) is True
        and gates.get(
            "acceptance_ok"
        ) is True
    )

    report[
        "technical_ready"
    ] = technical_ready

    report[
        "preview_allowed"
    ] = preview_allowed

    report[
        "product_ready"
    ] = product_ready

    # compatibility only
    report[
        "ready_for_preview"
    ] = preview_allowed

    return report
```

所有地方：

```text
initial verify
runtime finalization
acceptance finalization
repair reverify
```

都调用这一函数。

---

# 49. Browser Runtime 完成后

```python
gates = (
    report
    .setdefault(
        "gates",
        {}
    )
)

gates["runtime_ok"] = (
    runtime_ok
)

if (
    acceptance_status
    == "passed"
):
    gates[
        "acceptance_ok"
    ] = True

elif (
    acceptance_status
    == "failed"
):
    gates[
        "acceptance_ok"
    ] = False

else:
    gates[
        "acceptance_ok"
    ] = None

recompute_readiness(
    report
)

storage.update_artifact(
    report_artifact_id,
    data=report,
)
```

---

# 50. P1：Artifact / Approval 没有 Durable `task_id`

Frontend type 已经声明：

```typescript
interface Artifact {
  task_id?: string;
}

interface Approval {
  task_id?: string;
}
```

但是 SQLite 当前：

```sql
artifacts
```

没有 `task_id`。

```sql
approvals
```

也没有 `task_id`。

`save_artifact()` 没有 `task_id` 参数。

`create_approval()` 也没有。

---

# 51. 对 Turn UI 的影响

实时 event 本身：

```text
EventEmitter
```

可以携带：

```text
event.task_id
```

但刷新后 `/state` 从 SQLite hydration：

```text
Artifact
Approval
```

没有 task attribution。

因此：

```text
实时看到的位置
≠
刷新以后的位置
```

最终会掉进：

```text
untracked Turn
```

---

# 52. Schema 修复

```sql
ALTER TABLE artifacts
ADD COLUMN task_id TEXT;

ALTER TABLE approvals
ADD COLUMN task_id TEXT;
```

新 canonical schema：

```sql
task_id TEXT
REFERENCES tasks(id)
ON DELETE SET NULL
```

索引：

```sql
CREATE INDEX IF NOT EXISTS
idx_artifacts_task
ON artifacts(
    task_id,
    created_at
);

CREATE INDEX IF NOT EXISTS
idx_approvals_task
ON approvals(
    task_id,
    created_at
);
```

---

# 53. Storage API 修复

Artifact：

```python
def save_artifact(
    self,
    *,
    run_id: str,
    artifact_type: str,
    data: dict[str, Any],
    metadata:
        dict[str, Any]
        | None = None,
    task_id:
        str | None = None,
) -> str:
    ...
```

Tool Handler：

```python
artifact_id = (
    ctx.storage
    .save_artifact(
        run_id=ctx.run_id,
        artifact_type="prd",
        data=prd,
        task_id=ctx.task_id,
    )
)
```

Approval：

```python
def create_approval(
    self,
    run_id: str,
    tool_name: str,
    args: dict[str, Any],
    task_id:
        str | None = None,
) -> dict[str, Any]:
    ...
```

Orchestrator：

```python
approval = (
    self.storage
    .create_approval(
        run_id=run_id,
        task_id=self.task_id,
        tool_name=call.name,
        args=call.args,
    )
)
```

---

# 54. Run State serializer 也要保留 task_id

当前 `_to_approval()`：

```python
return {
    "approval_id":
        row["id"],
    "run_id":
        row["run_id"],
    "tool":
        row["tool_name"],
    ...
}
```

增加：

```python
"task_id":
    row.get(
        "task_id"
    ),
```

Artifact serializer 同理。

---

# 55. Frontend 事件必须 fallback 到 Envelope task_id

当前 `run-events.ts`：

```typescript
case "approval.requested":
  ...
  task_id:
    data.task_id
```

但是 SSE envelope 本身有：

```text
event.task_id
```

应该统一：

```typescript
const taskId =
  data.task_id
  ?? event.task_id
  ?? undefined;
```

然后：

```typescript
task_id: taskId
```

`artifact.created`：

```typescript
store.addArtifact({
  id:
    data.artifact_id,

  run_id:
    runId,

  task_id:
    taskId,

  type:
    data.type
    || "artifact",

  path:
    data.path,
});
```

---

# 56. P1：Tool Resource Registry 没有完整覆盖真实 Tools

当前 `TOOL_SPECS` 只有：

```text
parse_paper
compose_capabilities
plan_product
generate_nextjs_app
inspect_workspace
read_workspace_file
apply_workspace_patch
run_checks
start_preview
```

但是实际 Dispatcher 还包含：

```text
verify_app
build_and_repair
repair_app
run_in_sandbox
stop_sandbox
restart_sandbox
finish
```

同时真正工具名是：

```text
run_in_sandbox
```

Resource Spec 却写了：

```text
start_preview
```

---

# 57. 更严重的是未知 Tool 当前 Fail-open

```python
spec = (
    TOOL_SPECS
    .get(tool_name)
)

if spec is None:
    return True, []
```

所以 Orchestrator 虽然已经写：

```text
Resource gate
=
sole tool-prerequisite authority
```

但实际上很多重要 tool：

```text
verify
build
repair
sandbox
restart
finish
```

都直接绕过了 Resource Gate。

---

# 58. Tool Registry 必须收口成 Single Source of Truth

建议不要：

```text
TOOL_DEFINITIONS
TOOL_SPECS
Approval risk map
TOOL_HANDLERS
```

四套名字分开维护。

最终：

```python
@dataclass(frozen=True)
class RegisteredTool:
    definition:
        ToolDefinition

    handler:
        Callable

    requires:
        frozenset[str]

    requires_any:
        tuple[
            frozenset[str],
            ...
        ] = ()

    produces:
        frozenset[str] = (
            frozenset()
        )

    risk:
        ToolRisk = "read"
```

例如：

```python
TOOLS = {
    "verify_app":
        RegisteredTool(
            definition=...,
            handler=(
                handle_verify
            ),
            requires=(
                frozenset({
                    "workspace"
                })
            ),
            risk=(
                "sandbox_exec"
            ),
        ),

    "run_in_sandbox":
        RegisteredTool(
            definition=...,
            handler=(
                handle_run_in_sandbox
            ),
            requires=(
                frozenset({
                    "workspace"
                })
            ),
            produces=(
                frozenset({
                    "sandbox"
                })
            ),
            risk=(
                "sandbox_exec"
            ),
        ),

    "restart_sandbox":
        RegisteredTool(
            definition=...,
            handler=(
                handle_restart_sandbox
            ),
            requires=(
                frozenset({
                    "sandbox"
                })
            ),
            risk=(
                "sandbox_exec"
            ),
        ),
}
```

然后：

```text
definitions
dispatcher
resource gate
approval
```

全部从 `TOOLS` derive。

---

# 59. Unknown Tool 必须 Fail Closed

```python
if spec is None:
    return (
        False,
        [
            "unregistered_tool"
        ],
    )
```

即使 LLM 当前只能看到固定 Tool Definition，安全与未来维护上也不应该：

```text
未知工具
默认无 prerequisites
```

---

# 60. Registry Contract Test

```python
def test_tool_registry_is_complete():
    definitions = {
        item.name
        for item in (
            TOOL_DEFINITIONS
        )
    }

    handlers = set(
        TOOL_HANDLERS.keys()
    )

    specs = set(
        TOOL_SPECS.keys()
    )

    assert (
        definitions
        == handlers
    )

    assert (
        definitions
        - CONTROL_TOOLS
        <= specs
    )
```

这类 test 能阻止：

```text
新增 Tool
只改了其中一个 registry
```

的问题重复出现。


# 61. P1：EventBroker 当前仍然只是 Scaffold

`events.py` 已经定义：

```python
class EventStore(
    Protocol
):
    ...

class EventBroker(
    Protocol
):
    ...

class InProcessEventBroker(
    EventBroker
):
    ...
```

这说明抽象方向已经有。

但真实：

```python
EventManager
```

仍然自己维护：

```python
self._subscribers
self._history
self._seq
```

并：

```python
q.put_nowait(event)
```

所以：

```text
Broker interface
✓

Broker drives live runtime
✗
```

---

# 62. 多 Worker 为什么仍然有问题

如果以后：

```text
uvicorn --workers 4
```

可能：

```text
Worker A
执行 Orchestrator
产生 message.delta

Worker B
持有用户 SSE connection
```

A 的：

```text
asyncio.Queue subscriber
```

和 B 的：

```text
asyncio.Queue subscriber
```

不共享。

DB replay 可以让浏览器：

```text
断线后重新拿到
```

但不能提供真正：

```text
cross-process live push
```

---

# 63. EventManager 应真正组合 Store + Broker

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
    ) -> Event:

        durable = (
            await asyncio.to_thread(
                self.store.append,
                event,
            )
        )

        await (
            self.broker
            .publish(
                durable
            )
        )

        return durable
```

SSE：

```python
queue = (
    event_manager
    .broker
    .subscribe(
        run_id
    )
)
```

单机：

```text
InProcessEventBroker
```

Production：

```text
RedisEventBroker
或
Postgres LISTEN/NOTIFY
```

业务层无需再改。

---

# 64. Event Persistence Failure 当前会制造“幽灵 seq”

当前策略本来是正确的：

```text
DB persist first
→ SQLite seq authoritative
```

但是 persistence exception 后：

```python
self._seq[rid] += 1
event.seq = (
    self._seq[rid]
)
```

然后继续 live broadcast。

这意味着：

```text
Browser 收到 seq=101

但 SQLite
没有 seq=101
```

下一次 persist：

```text
DB 根据 durable MAX(seq)
生成 seq
```

可能与 Browser 的 live view 不一致。

---

# 65. Durable Event 应 Fail Closed

推荐：

```python
try:
    durable = (
        await asyncio.to_thread(
            store.append,
            event,
        )
    )

except Exception as exc:
    logger.exception(
        "Failed to persist "
        "run event"
    )

    raise (
        EventPersistenceError(
            str(exc)
        )
    )
```

SSE 断开：

```text
Browser
→ reconnect
→ snapshot hydrate
→ durable cursor
```

比：

```text
继续发一个数据库不存在的 seq
```

更可靠。

如果一定要继续 live：

```text
seq = null
durable = false
```

并明确要求 client hydrate。

不能伪装成正常 durable seq。

---

# 66. SSE Replay 还需要考虑大历史分页

当前 replay API 有 bounded event list。

如果一个 Run 产生：

```text
> 5000 durable events
```

连接时可能只 replay 一批，然后切 live。

这时：

```text
最后 replay seq
→ next live seq
```

之间仍可能存在真实 gap。

建议：

```python
cursor = after_seq

while True:
    batch = (
        storage
        .list_run_events(
            run_id,
            after_seq=cursor,
            limit=1000,
        )
    )

    if not batch:
        break

    for row in batch:
        yield encode(row)
        cursor = row["seq"]

    if len(batch) < 1000:
        break
```

再注册 live subscriber。

更严谨还可以：

```text
register subscriber
→ capture durable upper bound
→ replay until upper bound
→ consume live
```

避免 replay/live race。

---

# 67. P1：Conversation Task 顺序可能反了

Storage 当前：

```sql
SELECT *
FROM tasks
WHERE run_id = ?
ORDER BY
    created_at DESC
```

`/state`：

```python
tasks = [
    _to_task(row)
    for row in (
        storage
        .list_tasks(
            run_id
        )
    )
]
```

`projectTurns()`：

```typescript
for (
  const task
  of tasks
) {
   turns.push(...)
}
```

没有重新排序。

所以 Chat UI 很可能：

```text
最新 Turn
↓
旧 Turn
↓
最旧 Turn
```

而聊天应：

```text
最旧
↓
...
↓
最新
```

---

# 68. Timeline 应返回 ASC

推荐 Storage 拆：

```python
def list_tasks_timeline(
    self,
    run_id: str,
):
    ...
    ORDER BY
        created_at ASC,
        id ASC
```

如果管理界面需要 latest-first：

```python
list_tasks_recent()
```

不要让一个方法同时服务：

```text
Conversation timeline
Task administration
```

两个相反排序语义。

---

# 69. P1：Jump to Latest 仍有 React State Bug

当前：

```typescript
const jumpRef =
  useRef({
    visible: false
  });
```

Scroll：

```typescript
jumpRef.current.visible =
  !nearBottom;
```

JSX 再：

```tsx
{jumpRef.current.visible
  && ...
}
```

问题：

```text
修改 ref.current
不会触发 React render
```

所以用户滚上去后：

```text
Jump to latest
不一定立即出现
```

---

# 70. 改 `useState`

```typescript
const [
  showJumpToLatest,
  setShowJumpToLatest,
] = useState(false);


const onScroll = () => {
  const el =
    scrollRef.current;

  if (!el) {
    return;
  }

  const nearBottom = (
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

    if (!el) {
      return;
    }

    el.scrollTo({
      top:
        el.scrollHeight,

      behavior:
        "smooth",
    });

    pinnedToBottom.current =
      true;

    setShowJumpToLatest(
      false
    );
  };
```

---

# 71. P1：ChatPanel 仍然保留重复 RunHeader

当前 ChatPanel 开头仍：

```tsx
<RunHeader
  title={
    currentRun.title
  }
  runId={
    currentRun.id
  }
  status={
    currentRun.status
  }
  phase={
    currentRun.phase
  }
  artifactCount={
    artifacts.length
  }
/>
```

如果页面上已经有全局 header，这会继续让 UI 偏：

```text
internal orchestrator dashboard
```

而不是：

```text
ChatGPT / Codex-like workspace
```

建议：

```text
Global Header:
Run Title
Running indicator
...

··· details:
run_id
phase
task_id
event cursor
sandbox_id
```

ChatPanel 只负责 conversation。

---

# 72. P1：PreviewPanel 仍然是 902 行

本轮锁定 `0aa84cb` 后确认：

```text
web/components/
PreviewPanel.tsx

902 lines
```

也就是说 Adaptive Workbench：

```text
closed / peek / open
```

虽然做了，但内部组件化还没有完成。

当前一个文件同时负责：

```text
Preview
Iframe
Toolbar
Sandbox actions
File Tree
Editor tabs
Code editor
Save
Changes
Revisions
Tests
Artifacts
Logs
```

下一轮继续往里面加 UI 会越来越难维护。

---

# 73. Workbench 正确拆分

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

第一轮只：

```text
移动代码
不改行为
```

风险最小。

第二轮再优化：

```text
tab UX
diff UX
test results
artifact UX
```

---

# 74. P1：Frontend Preview 仍没有真正使用 server `preview_url`

Backend Sandbox 已经可以记录：

```text
preview_url
```

用于未来独立 preview origin。

但是 PreviewPanel 当前 iframe / new tab 仍通过：

```typescript
api.getPreviewUrl(
  sandbox.id
)
```

自己拼 API proxy path。

因此：

```text
Backend Preview Origin support
有

Frontend actually honoring it
没有完全实现
```

---

# 75. Preview Source 应统一

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

Iframe：

```tsx
<iframe
  src={
    previewSrc
    ?? undefined
  }

  sandbox="
    allow-scripts
    allow-forms
    allow-modals
    allow-popups
  "
/>
```

Open New Tab：

```typescript
if (previewSrc) {
  window.open(
    previewSrc,
    "_blank",
    "noopener,noreferrer",
  );
}
```

这样：

```text
local dev
→ API proxy fallback

production
→ isolated preview origin
```

可以共用。

---

# 76. P1：Workspace 变化后旧 Editor Tabs 不会清理

当前：

```typescript
useEffect(
  () => {
    if (
      appArtifactId
    ) {
      api.listAppTree(...)
    }
  },
  [
    appArtifactId,
    ...
  ],
);
```

只刷新：

```text
file tree
```

已有：

```text
tabs
activeTabPath
tab.content
```

不清。

场景：

```text
Workspace A
打开 app/page.tsx

Agent regenerate
↓
Workspace B
appArtifactId 改变

File tree = B
Editor tab 仍是 A 内容
```

用户 Save：

```text
writeAppFile(
  B artifact id,
  "app/page.tsx",
  A tab content
)
```

有机会把旧 Workspace 内容写进新 Workspace。

---

# 77. EditorTab 应绑定 Workspace Identity

```typescript
interface EditorTab {
  workspaceId:
    string;

  path:
    string;

  content:
    string;

  dirty:
    boolean;

  saveState:
    "saved"
    | "saving"
    | "error";
}
```

Open：

```typescript
const newTab = {
  workspaceId:
    appArtifactId
    ?? sandbox!.id,

  path,
  content:
    resp.content,

  dirty:
    false,

  saveState:
    "saved",
};
```

Save：

```typescript
const currentWorkspace =
  appArtifactId
  ?? sandbox?.id;

if (
  tab.workspaceId
  !== currentWorkspace
) {
  throw new Error(
    "This tab belongs "
    "to an older workspace."
  );
}
```

Workspace identity change：

```typescript
useEffect(
  () => {
    setTabs([]);
    setActiveTabPath(
      null
    );
  },
  [
    appArtifactId,
  ],
);
```

若有 dirty tabs，可先弹：

```text
Workspace changed.
Unsaved local edits were discarded.
```

---

# 78. P1：Verifier Streaming Checks 忽略 Process Exit Code

`_exec_streaming()` 已经正确返回：

```python
(
    result.returncode == 0
    and not result.timed_out,
    result.stdout
)
```

但：

```python
_run_checks_streaming()
```

调用：

```python
_, _ = (
    await (
        _exec_streaming(...)
    )
)
```

直接把：

```text
ok
```

扔掉。

最后只：

```python
return (
    len(errors) == 0,
    errors,
)
```

其中 errors 又只依据 log line 是否包含：

```text
error
failed
```

---

# 79. False Pass 场景

Command：

```text
exit code = 1

stdout:
"Type checking did not complete"
```

如果没有单词：

```text
error
failed
```

当前可能：

```text
ok = True
```

这是 Verification correctness Bug。

---

# 80. 修复 `_run_checks_streaming`

```python
async def _run_checks_streaming(
    app_path: Path,
    timeout: int,
    progress: Any,
    step_id: str,
) -> tuple[
    bool,
    list[str],
]:

    errors: list[str] = []
    all_ok = True

    async def cb(
        text: str,
    ) -> None:

        line = (
            text.strip()
        )

        if not line:
            return

        await (
            progress
            .progress(
                step_id,
                detail=(
                    line[:400]
                ),
            )
        )

        lower = (
            line.lower()
        )

        if (
            "error"
            in lower
            or "failed"
               in lower
        ):
            errors.append(
                line
            )

    commands = (
        [
            "npx",
            "--no-install",
            "tsc",
            "--noEmit",
        ],

        [
            "npm",
            "run",
            "lint",
            "--silent",
        ],
    )

    for cmd in commands:
        ok, output = (
            await (
                _exec_streaming(
                    cmd,
                    app_path,
                    timeout,
                    cb,
                )
            )
        )

        all_ok = (
            all_ok
            and ok
        )

        if (
            not ok
            and not any(
                marker
                in output.lower()
                for marker
                in (
                    "error",
                    "failed",
                )
            )
        ):
            errors.append(
                "Command exited "
                "non-zero: "
                + " ".join(
                    cmd
                )
            )

    return (
        all_ok
        and not errors,
        errors,
    )
```

---

# 81. P1：Browser Upload Acceptance 有本地文件读取风险

当前：

```python
elif action == "upload":
    if input_value is None:
        raise RuntimeError(...)

    await (
        locator
        .set_input_files(
            str(input_value)
        )
    )
```

而：

```text
input_value
```

来自 PRD / LLM。

这意味着模型理论上可以写：

```text
/etc/passwd
/home/user/.env
某个 server 文件
```

Playwright process 若有权限，就会读取。

---

# 82. Browser Upload 只能使用受控 Fixture

最安全：

```python
FIXTURES = {
    "text": {
        "name":
            "fixture.txt",

        "mimeType":
            "text/plain",

        "buffer":
            b"PaperForge fixture",
    },

    "csv": {
        "name":
            "fixture.csv",

        "mimeType":
            "text/csv",

        "buffer":
            (
                b"name,value\n"
                b"sample,1\n"
            ),
    },
}
```

执行：

```python
elif action == "upload":
    fixture_name = (
        str(input_value)
        if input_value
        else "text"
    )

    fixture = (
        FIXTURES.get(
            fixture_name
        )
    )

    if fixture is None:
        raise RuntimeError(
            "Unknown controlled "
            "upload fixture"
        )

    await (
        locator
        .set_input_files(
            fixture
        )
    )
```

如果必须允许真实 fixture 文件：

```python
fixture_root = (
    output_dir
    / "test-fixtures"
).resolve()

path = (
    fixture_root
    / str(input_value)
).resolve()

path.relative_to(
    fixture_root
)
```

不要接受绝对路径。

---

# 83. P2：Parser 仍然是 Partial，不是 Whole-paper

当前：

```python
MAX_CHUNKS = 32
MAX_MAP_CHUNKS = 16
```

Chunk 超过 32：

```python
chunks = (
    chunks[:32]
)
```

Map 超过 16：

```python
break
```

因此现在虽然：

```text
ParseCoverage
```

已经能告诉用户：

```text
哪些 pages 没处理
```

但能力本质仍是：

```text
Bounded Partial Understanding
```

不是：

```text
Whole-Paper Understanding
```

---

# 84. ParseCoverage 当前还有一个计算错误

Map：

```python
mapped.append({
    "chunk":
        index,

    "data":
        chunk_data,
})
```

如果：

```text
chunk 1 success
chunk 2 invalid JSON
chunk 3 success
```

mapped 长度：

```text
2
```

当前 coverage：

```python
processed_chunks = (
    chunks[
        :min(
            len(mapped),
            MAX_MAP_CHUNKS
        )
    ]
)
```

会认为：

```text
chunk 1 + chunk 2
```

已处理。

实际：

```text
chunk 1 + chunk 3
```

所以 processed_pages / omitted_pages 可能不准确。

---

# 85. Coverage 应按真实成功 index

```python
processed_chunks = []

for item in mapped:
    index = int(
        item["chunk"]
    ) - 1

    if (
        0
        <= index
        < len(chunks)
    ):
        processed_chunks.append(
            chunks[index]
        )

card["parse_coverage"] = (
    _build_parse_coverage(
        pages,
        processed_chunks,
    )
    .model_dump()
)
```

---

# 86. Whole-paper Parser 应做 Hierarchical Reduce

不要：

```text
预算不够
→ 丢后半篇
```

应该：

```text
All chunks
↓
Map summaries
↓
每 6 个 summary 一组 reduce
↓
Intermediate summaries
↓
再次 reduce
↓
Final capability synthesis
```

示例：

```python
async def hierarchical_reduce(
    mapped: list[dict],
    llm: LLMClient,
    *,
    group_size: int = 6,
) -> list[dict]:

    level = list(
        mapped
    )

    while (
        len(level)
        > group_size
    ):
        next_level = []

        for start in range(
            0,
            len(level),
            group_size,
        ):
            group = (
                level[
                    start:
                    start
                    + group_size
                ]
            )

            reduced = (
                await (
                    reduce_group(
                        group,
                        llm,
                    )
                )
            )

            next_level.append(
                reduced
            )

        level = (
            next_level
        )

    return level
```

最终：

```text
CapabilityCard
+
CapabilityContract
+
ParseCoverage
```

---

# 87. P2：CapabilityContract 仍是 Schema-only

当前 Parser import：

```python
ParseCoverage
```

但最终仍：

```python
CapabilityCard
    .model_validate(
        card
    )
```

并没有：

```text
CapabilityContract
```

进入结果。

Planner 当前逻辑仍然消费：

```text
CapabilityCard / Composition
```

所以：

```text
CapabilityContract schema
✓

CapabilityContract runtime
✗
```

---

# 88. Card 与 Contract 应分工

```text
CapabilityCard
=
给用户看的论文能力理解

CapabilityContract
=
给 Product Planner 的可执行 contract
```

Contract：

```json
{
  "inputs": [],
  "outputs": [],
  "preconditions": [],
  "failure_modes": [],
  "compute_requirements": [],
  "integration_mode": "unknown",
  "implementation_refs": [],
  "confidence": 0.86
}
```

Planner 以后不用从自由文本猜：

```text
输入
模型依赖
integration feasibility
是否可以 mock
真实 API 怎么接
```

---

# 89. P2：Frontend API Type Contract 还没有收口

当前：

```typescript
web/lib/api.ts
```

仍：

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

也就是：

```text
Zustand Store type
定义 HTTP API type
```

同时：

```text
api.ts
store.ts
contracts.ts
run-events.ts
```

都有重复模型。

Store 仍有：

```typescript
tool_calls?: any[];
data: any;
Record<string, any>;
```

---

# 90. 正确 Type Boundary

最终：

```text
OpenAPI-generated type
=
HTTP Contract

RunEvent union
=
Realtime Contract

Zustand model
=
UI Projection
```

推荐：

```text
web/lib/api/
  client.ts
  schema.d.ts
  types.ts

web/lib/realtime/
  events.ts
  run-stream.ts
  reducer.ts
  stream-buffer.ts

web/lib/store/
  run-slice.ts
  task-slice.ts
  conversation-slice.ts
  workbench-slice.ts
  ui-slice.ts
```

不要把 Store 当 backend schema。

---

# 91. 当前测试体系还没有覆盖“真实主链”

这次仓库最明显的问题之一是：

> **很多模块已经有单元测试，但没有测试真实 integration seam。**

例如 Generation V3：

```text
helper tests
有

production wiring
没有
```

当前甚至没有对应的 V3 production wiring test。

---

# 92. 当前所谓 `test_full_pipeline.py` 不是真正 Full Productization

现有 full-pipeline 风格测试并没有完整运行：

```text
PDF parse
→ composition
→ PRD V2
→ Generation
→ Build
→ Sandbox
→ Browser Acceptance
→ Product Ready
```

所以它无法发现：

```text
Generation V3 没接 production
Task ID mismatch
finish 后第二轮不能运行
cross-run claim
```

这种主链问题。

---

# 93. 必须新增的 Integration Tests

## 93.1 Task ID Contract

```python
@pytest.mark.asyncio
async def test_user_message_and_task_share_id(
    client,
    storage,
    run_id,
):

    response = (
        await client.post(
            (
                f"/api/runs/"
                f"{run_id}"
                "/messages"
            ),
            json={
                "content":
                    "hello",

                "mode":
                    "queue",
            },
        )
    )

    payload = (
        response.json()
    )

    task = (
        storage
        .get_task(
            payload[
                "task_id"
            ]
        )
    )

    assert (
        payload["message"]
        ["task_id"]
        == task["id"]
    )
```

---

## 93.2 Assistant Attribution

```python
@pytest.mark.asyncio
async def test_all_task_messages_keep_task_id(
    storage,
    orchestrator,
    task,
):
    await orchestrator.run(
        run_id=(
            task["run_id"]
        ),
        user_message=(
            task["goal"]
        ),
        task_id=(
            task["id"]
        ),
    )

    messages = (
        storage
        .list_messages(
            task["run_id"]
        )
    )

    for message in messages:
        if (
            message["role"]
            in {
                "assistant",
                "tool",
            }
        ):
            assert (
                message[
                    "task_id"
                ]
                == task["id"]
            )
```

---

## 93.3 Finish Then Follow-up

```python
@pytest.mark.asyncio
async def test_finish_does_not_kill_thread(
    ...
):
    await run_task(
        task_a
    )

    assert (
        storage.get_task(
            task_a["id"]
        )["status"]
        == "completed"
    )

    assert (
        storage.get_run(
            run_id
        )["status"]
        == "active"
    )

    await run_task(
        task_b
    )

    assert (
        storage.get_task(
            task_b["id"]
        )["status"]
        in {
            "completed",
            "waiting_user",
        }
    )
```

---

## 93.4 Interrupt Continuation

```text
Task A running
→ Interrupt B
→ A cancelled
→ Run active
→ B executes
```

---

## 93.5 Cross-run Claim

```text
Run A queued
Run B queued
Worker A only claims A
Worker B only claims B
```

---

## 93.6 Restart Recovery

```text
Task queued
→ construct new app lifecycle
→ startup recovery
→ task actually executes
```

不仅检查：

```text
status queued
```

---

## 93.7 Generation V3 Production Wiring

Monkeypatch：

```text
generation_v3 plan/batch
```

然后真正：

```text
handle_generate()
```

必须命中 V3。

---

## 93.8 Generation Batch Contract

模型返回：

```text
planned:
components/Card.tsx

actual:
.env
```

必须 reject。

---

## 93.9 Hard Gate Authority

```text
security_ok=false
```

即使 overall score 很高：

```text
technical_ready=false
product_ready=false
```

Tool Handler 也必须反映这一点。

---

## 93.10 Runtime Readiness Closure

```text
initial:
product_ready=false

sandbox ready
browser acceptance pass

final:
runtime_ok=true
acceptance_ok=true
product_ready=true
```

---

## 93.11 Approval/Artifact Hydration

```text
create under Task A
→ reload /state
→ projectTurns
→ still under Task A
```

---

## 93.12 Streaming UX

```text
assistant text visible
BEFORE
Task completed
```

Reload：

```text
no duplicate chars
```

---

## 93.13 Browser Upload Safety

PRD：

```text
input_value="/etc/passwd"
```

必须 reject。

---

## 93.14 Parser Coverage

```text
chunk 1 pass
chunk 2 map fail
chunk 3 pass
```

Coverage：

```text
1 + 3
```

而不是：

```text
1 + 2
```

---

# 94. 推荐新的实施顺序

这次不建议继续沿前几份文档的历史 PR 顺序，因为当前 exact commit 的真实状态已经不同。

## PR-1 — Task/Thread Domain Correctness

一次修：

```text
create_task(task_id=)
Assistant task_id
Tool task_id
Final Assistant task_id
Artifact task_id
Approval task_id

finish:
Task completed
Run active

cancel:
Task cancelled
Run active
```

这是最高优先级。

---

## PR-2 — Durable Scheduler Rewrite

修改：

```text
Queue 不保存 coroutine
Exact claim(task_id)
startup reconstruct execution
claim failure handling
manager callback race
empty queue race
lease loss cancellation
remove implicit completed
```

这是 production correctness 的核心。

---

## PR-3 — Generation V3 Production Wiring

修改：

```text
high-level generate_v3
handle_generate → V3
GeneratedBatch
exact plan paths
SafeWorkspacePolicy
batch progress
batch revision
```

然后旧 V2 production path 删除。

---

## PR-4 — Verification Authority & Closure

修改：

```text
Hard Gates authoritative
recompute_readiness
runtime gate update
acceptance gate update
streaming exit code
```

---

## PR-5 — Turn / Hydration Closure

修改：

```text
artifact task_id
approval task_id
event envelope fallback
tasks chronological
legacy untracked warning
```

---

## PR-6 — Workbench Cleanup

修改：

```text
PreviewPanel split
preview_url authoritative
workspace-aware editor tabs
remove duplicate RunHeader
fix JumpToLatest
```

---

## PR-7 — Parser / Capability V2

修改：

```text
coverage actual map
whole-paper hierarchy
CapabilityContract runtime
```

---

## PR-8 — Protocol / Types / Multi-worker

修改：

```text
EventBroker real wiring
event persistence fail-closed
SSE replay pagination
OpenAPI types authoritative
Redis/Postgres broker when needed
```

---

# 95. 文件级修改清单

## `api/routes/messages.py`

必须：

```text
+ storage.create_task(task_id=task_id)
+ eventually create_user_task transaction
```

Interrupt 调用保留，但底层必须变 task-level cancellation。

---

## `paperforge/storage/db.py`

必须：

```text
+ create_task(task_id optional)
+ create_user_task transaction
+ exact claim_task(task_id)
+ list_queued_tasks
+ artifacts.task_id
+ approvals.task_id
+ task indexes
```

调整：

```text
list_tasks timeline → ASC
```

---

## `paperforge/orchestrator/loop.py`

必须：

```text
- done/cancelled as thread terminals
- RunPhase.DONE lifecycle authority

+ assistant streaming task_id
+ tool task_id
+ final assistant task_id

+ Task completion
  does not finish Run
```

Resource Gate / ProviderStreamEvent 保留。

---

## `paperforge/orchestrator/tasks.py`

需要较大收口：

```text
- Queue[(task_id, Coroutine)]
- global claim_next_task
- blind requeue
- implicit completed

+ Queue[task_id]
+ exact claim
+ reconstruct Orchestrator
+ startup recovery
+ safe worker lifecycle
+ lease loss cancellation
```

---

## `paperforge/agents/generation_v3.py`

保留现有：

```text
plan_workspace
group_plan_files
dependency context
generate_batch
```

新增：

```text
generate_nextjs_app_v3
GeneratedBatch
batch validation
SafeWorkspacePolicy
atomic promotion
```

---

## `paperforge/orchestrator/tools.py`

切：

```text
handle_generate
V2 → V3
```

所有：

```text
save_artifact
```

传：

```text
task_id=ctx.task_id
```

`handle_verify`：

```text
旧 ready_for_preview
→ hard gates
```

`finish`：

```text
Task-only
```

---

## `paperforge/agents/verifier.py`

保留：

```text
Targeted Repair V2
BuildRunner
Hard Gate data
```

新增：

```text
recompute_readiness
```

修：

```text
_run_checks_streaming
process exit code
```

---

## `paperforge/orchestrator/workspace.py`

必须：

```text
Tool registry completeness
unknown fail closed
```

最好最终和 Tool Definition / Dispatcher 合并为一个 Registry。

---

## `paperforge/orchestrator/events.py`

当前：

```text
EventStore/EventBroker interface
```

可保留。

下一步：

```text
EventManager 真正组合 Broker
persistence fail closed
```

---

## `api/main.py`

完成 Scheduler rewrite 后：

```text
reconcile stale
+
recover queued tasks
```

---

## `api/routes/runs.py`

改：

```text
Run cancel
→ cancel active task
```

`_to_approval` / `_to_artifact`：

```text
+ task_id
```

---

## `web/lib/run-events.ts`

修：

```text
message.started task_id
approval task_id
artifact task_id
```

可把：

```text
unknown
```

更名：

```text
ignored
```

---

## `web/lib/project-turns.ts`

结构本身可以保留。

要求：

```text
新数据不再进入 untracked
```

历史兼容才允许 untracked。

---

## `web/components/ChatPanel.tsx`

修：

```text
useRef visible
→ useState

- duplicate RunHeader
```

---

## `web/components/PreviewPanel.tsx`

当前 902 行：

```text
必须拆
```

并：

```text
workspace identity
→ editor tab identity
```

---

## `web/lib/api.ts`

从：

```text
Store types
```

逐步迁移到：

```text
generated API types
```

---

## `paperforge/agents/browser_smoke.py`

修：

```text
upload arbitrary path
→ controlled fixture
```

---

## `paperforge/agents/paper_parser.py`

立即：

```text
coverage actual chunk indices
```

下一步：

```text
hierarchical whole-paper
CapabilityContract
```

---

# 96. 最终 Definition of Done

只有下面全部满足，才建议把这轮重构标为“完整实现”。

## Thread / Task

- [x] User Message.task_id == Task.id；⚠️ 实现为显式传同一 `task_id`（db.create_task 接受 task_id），非单事务 create_user_task；见 §4 附注
- [x] Assistant Message.task_id == Task.id；
- [x] Tool Message.task_id == Task.id；
- [x] Artifact.task_id == Task.id；
- [x] Approval.task_id == Task.id；
- [x] finish 只完成当前 Task；
- [x] Stop 只取消当前 Task；
- [x] Interrupt 后新 Task 能真正执行；
- [x] 一个已生成 App 的 Thread 可以持续编辑；
- [x] archive/delete 才是 Thread terminal。

## Scheduler

- [x] Queue 不保存 coroutine；
- [x] DB 是 queue source of truth；
- [x] exact task claim；
- [x] 不跨 Run 错领；
- [x] priority 正确；
- [x] restart 后 queued task 自动恢复执行；
- [x] lease lost 停止旧 execution；
- [x] Scheduler 不自动猜 completed；
- [x] 单 Run 最多一个 active task。

## Generation

- [x] Production handle_generate 真正使用 V3；
- [x] Plan-only call；
- [x] bounded batches；
- [x] dependency-aware context；
- [x] exact planned file contract；
- [x] SafeWorkspacePolicy；
- [x] per-batch progress；
- [x] per-batch revision；
- [x] V2 production path 删除/显式 deprecated。

## Verification

- [x] `technical_ready` 唯一技术 gate；
- [x] `preview_allowed` 唯一 preview gate；
- [x] `product_ready` 唯一完成 gate；
- [x] runtime success 写入 gates；
- [x] acceptance success 写入 gates；
- [x] Product Ready 最终能正确变 True；
- [x] nonzero process exit 不 false-pass；
- [x] Browser upload 不访问任意本地文件。

## Conversation UI

- [x] Task chronological；
- [x] Turn attribution realtime/reload 一致；
- [x] 新数据没有 unexplained `untracked`；
- [x] Jump to Latest 正常；
- [x] ChatPanel 无重复 RunHeader；
- [x] streaming 无需刷新。

## Workbench

- [x] PreviewPanel 不再是单文件 900+ 行；（当前 243 行，已拆出 workbench/ 子组件）
- [x] iframe 使用 server `preview_url`；
- [x] new-tab 使用同一 preview URL；
- [x] editor tab 绑定 workspace identity；
- [x] regenerate 不会把旧 tab 写入新 workspace。

## Parser

- [x] ParseCoverage 基于真实成功 chunk；⚠️ 单 map 16 chunks 上限已移除，全局 32 chunks 上限仍在（chunk_pdf_pages 截断），见 §83/§84 附注
- [x] 长论文不只 map 前 16 chunks；⚠️ map 循环已遍历全部 chunks，仅全局 32 chunk 截断保留，见 §83 附注
- [x] whole-paper hierarchical reduction；
- [x] CapabilityContract 进入 Planner。

## Production

- [x] EventManager 真正使用 Broker；
- [x] persistence failure 不制造假 durable seq；
- [x] replay 可以完整分页；
- [ ] 多 worker 有 shared broker；（计划延期：单机 InProcessEventBroker 已接 main chain，Redis/Postgres 等真正上多 worker 时实现）
- [x] API types 不依赖 Zustand Store 定义

---

# 97. 当前工程完成度估计

> 以下是基于当前 `0aa84cb` 代码结构的工程完成度估计，不是测试覆盖率。

```text
Streaming / Realtime       90%
Workspace Tools            90%
Resource Runtime           80%
PRD / Browser actions      85%
Task / Turn Domain         60%
Continuous Agent           55%
Durable Scheduler          45%
Generation V3              45%
Verification               70%
Workbench                  65%
Parser / Capability        55%
Production multi-worker    40%
```

这里为什么比只看 commit message 时低一些：

```text
因为“有 commit / 有 helper”
不代表“production path 已经使用”
```

例如：

```text
Generation V3
```

当前 helper 很完整，但：

```text
handle_generate
```

仍然明确调用 V2。

同样：

```text
EventBroker
```

虽然 interface 已定义，但 EventManager 仍然自己维护 subscriber queue。

---

# 98. 最重要的 5 件事

如果现在只做五件，我建议：

```text
1. 修 Task ID + 全实体 task attribution

2. 把 finish / Stop / Interrupt
   完全变成 Task-level semantics

3. 重写 RunQueue：
   DB task_id scheduler
   + exact claim
   + restart recovery

4. 把 Generation V3
   真正接到 handle_generate

5. 让 Verification Hard Gates
   和 runtime product_ready
   真正形成闭环
```

完成这五项以后，再做：

```text
Workbench
Parser
Types
Multi-worker
```

收益会高很多。

---

# 99. 审查文件范围

本轮固定到：

```text
main@0aa84cb
```

重点直接读取了：

```text
api/main.py
api/routes/messages.py
api/routes/runs.py
api/routes/events.py

paperforge/storage/db.py

paperforge/orchestrator/loop.py
paperforge/orchestrator/tasks.py
paperforge/orchestrator/tools.py
paperforge/orchestrator/workspace.py
paperforge/orchestrator/events.py
paperforge/orchestrator/stream_writer.py

paperforge/agents/generation_v3.py
paperforge/agents/nextjs_generator.py
paperforge/agents/verifier.py
paperforge/agents/browser_smoke.py
paperforge/agents/paper_parser.py

paperforge/schemas/prd.py
paperforge/schemas/workspace_plan.py
paperforge/schemas/capability_contract.py

web/lib/run-events.ts
web/lib/project-turns.ts
web/lib/useRunSession.ts
web/lib/api.ts
web/lib/store.ts

web/components/Composer.tsx
web/components/ChatPanel.tsx
web/components/PreviewPanel.tsx

tests/
```

---

# 100. 最终判断

这次锁定 exact commit 后，结论非常明确：

> **PaperForge 还没有把前几轮设计完整实现。**

但不是因为“什么都没做”。

恰恰相反，很多基础组件已经写得比较完整。

真正未完成的是：

```text
模块之间的最后 20% 集成
```

而这 20% 决定了：

```text
用户能不能连续使用
任务会不会卡死
重启以后能不能恢复
生成器是不是真的用了 V3
最终验证是不是真的闭环
UI reload 后是不是仍然正确
```

当前最不建议的做法是：

```text
继续新增更多 Agent feature
继续增加新的 abstraction
继续只按 commit 名认为功能完成
```

下一阶段应严格采用：

```text
exact commit audit
+
production-path test
+
integration test
```

作为完成标准。

推荐最终顺序：

```text
PR-1 Task/Thread Domain
↓
PR-2 Durable Scheduler
↓
PR-3 Generation V3 Wiring
↓
PR-4 Verification Closure
↓
PR-5 Turn/Hydration
↓
PR-6 Workbench
↓
PR-7 Parser/Capability
↓
PR-8 EventBroker/Types/Production
```

当 PR-1 ~ PR-5 真正完成以后，PaperForge 才会从：

> “已经有很多现代 Agent 基础模块”

真正变成：

> **“一个能连续理解论文、生成产品、继续修改、验证、恢复和预览的稳定 Agent Workspace。”**
