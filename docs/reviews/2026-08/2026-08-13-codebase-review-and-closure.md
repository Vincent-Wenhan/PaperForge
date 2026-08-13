# PaperForge 2026-08-13 全仓库复审与最终收口修复方案

> **复审日期：2026-08-13**  
> **仓库：** `Vincent-Wenhan/PaperForge`  
> **分支：** `main`  
> **本轮复审锚点：** GitHub 当前可见最新提交 `0aa84cb` — `feat(sandbox): disable container network by default`  
> **复审目标：** 不重复已经落地的重构，而是重新沿真实主链检查“现在还能不能跑、能不能连续跑、重启后能不能恢复、最终状态是否闭环”，并给出可以直接继续实现的代码级修复方案。

---

# 0. 结论先行

PaperForge 当前已经明显跨过“架构搭建期”，进入 **Integration Closure / Runtime Correctness** 阶段。

前几轮要求的很多模块现在都已经真正存在并进入主链：

```text
✓ StreamWriter
✓ ProviderStreamEvent
✓ SSE replay + seq
✓ frontend rAF stream buffer
✓ Resource Gate authoritative
✓ Workspace Tools
✓ Safe workspace patch
✓ Task / Step
✓ Queue / Interrupt
✓ exact task claim
✓ startup queued-task recovery
✓ Generation V3 wiring
✓ Verification hard-gate fields
✓ Targeted repair
✓ Browser acceptance action executor
✓ Turn projection
✓ Adaptive Workbench
✓ PreviewPanel 大幅拆分
✓ EventBroker abstraction 已接 EventManager
✓ event persistence fail-closed
✓ sandbox hardening / network default-off
✓ metrics
```

因此，这一轮**不应该再新增一套新的 Agent 架构**。

现在需要解决的是几个体量不大、但会直接破坏主流程的 integration seam：

```text
P0-1  Generation V3 在真实 batch 写文件时有直接 TypeError
P0-2  Interrupt / Stop 仍把整个 Run 置为 cancelled，破坏 persistent thread
P0-3  Preview/Browser Smoke 完成后没有重新计算 product_ready

P1-1  RunTaskManager replacement callback 有竞态
P1-2  RunQueue worker 退出与 enqueue 有丢唤醒/丢队列竞态
P1-3  claim 失败后盲目 requeue，可能把别的 worker 正在执行的 Task 改回 queued
P1-4  lease 丢失只停 heartbeat，不停正在执行的 Orchestrator
P1-5  Queue 在 finally 中把残留 running Task 自动标 completed，可能伪完成
P1-6  Generation V3 batch 输出没有严格 SafeWorkspacePolicy / plan-path contract
P1-7  Approval 的 task_id 在 hydration 与 realtime reducer 中仍会丢
P1-8  Task 列表 newest-first，Turn Projection 不排序，Conversation 顺序可能倒置
P1-9  Streaming verifier 丢弃 command exit code
P1-10 Browser upload criterion 允许 LLM 指定任意本地文件路径
P1-11 verify_app Resource Gate 允许只有 PRD、没有 workspace 的状态
P1-12 Workspace identity 变化后旧 editor tabs 不清理
P1-13 Open-in-new-tab 绕过 server-provided isolated preview origin

P2-1  Parser 仍是 bounded partial understanding，不是 whole-paper hierarchy
P2-2  ParseCoverage 对失败 map chunk 的 processed pages 计算可能错误
P2-3  CapabilityContract 仍未成为 Planner runtime contract
P2-4  OpenAPI schema 已生成，但前端 API/store 仍存在明显 type duplication / any
P2-5  默认 Broker 仍是 in-process；多 worker 需要 Redis/Postgres broker
```

这意味着：

> **PaperForge 离这一轮重构完成已经不远，但必须停止“继续加 feature”，先做一次严格的主链 integration closure。**

---

# 1. 当前真实完成状态

## 1.1 已经真正完成，不要重复重构的部分

| 模块 | 当前状态 | 结论 |
|---|---|---|
| Backend text streaming | ✅ | `StreamWriter` 已接主链 |
| Provider-neutral streaming | ✅ | Orchestrator 已消费 `ProviderStreamEvent` |
| SSE seq/replay | ✅ | durable replay 已有 |
| Frontend delta batching | ✅ | rAF buffer 已有 |
| Resource Gate | ✅ | 已替代 Phase permission |
| `RunPhase.DONE` 作为权限 | ✅ 已移除 | Phase 只用于 UI/display |
| Workspace Tools | ✅ | inspect/read/patch/check 已实现 |
| User Message ↔ Task ID | ✅ | 当前 `create_task(task_id=...)` 已修 |
| Assistant/Tool Message task_id | ✅ 大部分 | Orchestrator 主路径已带 |
| Queue stores task_id | ✅ | 不再把 coroutine 当队列数据 |
| exact claim | ✅ | `claim_task(task_id=...)` 已有 |
| startup recovery | ✅ 基础版 | queued rows 会重新 enqueue |
| Generation V3 wiring | ✅ | `handle_generate()` 已调用 V3 |
| Verification hard gates | ✅ 数据层 | Handler 已读取 |
| EventBroker integration | ✅ | EventManager 已组合 broker |
| Adaptive Workbench | ✅ | closed / peek / open |
| PreviewPanel modularization | ✅ 大幅完成 | 主文件约 212 行 |
| isolated preview URL | ✅ iframe | 仍有 new-tab 小问题 |
| Browser route/fill/select/upload | ✅ 功能 | upload 有安全问题 |

---

# 2. P0-1：Generation V3 当前真实主链会直接 TypeError

这是本轮最明确、最应该第一时间修的 Bug。

## 2.1 当前定义

`paperforge/agents/generation_v3.py`：

```python
def write_batch_files(
    workspace: Path,
    batch: dict[str, Any],
) -> list[str]:
    changed: list[str] = []

    for file in batch.get(
        "files",
        [],
    ):
        path = file.get("path")
        content = file.get("content")

        if (
            not path
            or content is None
        ):
            continue

        target = (
            workspace / path
        ).resolve()

        if (
            workspace.resolve()
            not in target.parents
            and target
                != workspace.resolve()
        ):
            logger.warning(
                "Refusing to write "
                "outside workspace: %s",
                path,
            )
            continue

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_text(
            content,
            encoding="utf-8",
        )

        changed.append(path)

    return changed
```

函数参数叫：

```text
workspace
```

但真实 V3 主流程调用：

```python
changed = write_batch_files(
    root=temp_dir,
    batch=batch,
)
```

因此第一个 batch 完成 LLM 生成以后会直接：

```text
TypeError:
write_batch_files()
got an unexpected keyword argument 'root'
```

## 2.2 修复

最小修复：

```python
changed = write_batch_files(
    workspace=temp_dir,
    batch=batch,
)
```

建议不要只改这一行，还要立刻加一个**真正执行完整 V3** 的 integration test，因为当前测试为什么没发现它，正是当前测试策略需要解决的问题。

---

# 3. 为什么现有 Generation V3 测试没抓到这个 Bug

当前测试大体分成两类：

```text
test_generation_v3.py
→ 测单个 helper / batch

test_generation_v3_wiring.py
→ mock 整个 generate_nextjs_app_v3()
→ 只验证 handle_generate 走 V3
```

所以：

```text
write_batch_files() 单独可用      ✓
handle_generate 调用了 V3         ✓
完整 V3 从 Plan 到写文件真正跑过   ✗
```

也就是说：

> 每个零件都测试了，但没有测试“把零件组装起来以后能不能跑”。

## 3.1 必须补一条 Full V3 integration test

```python
@pytest.mark.asyncio
async def test_generate_nextjs_app_v3_executes_full_path(
    storage,
    monkeypatch,
    tmp_path,
):
    from paperforge.agents import (
        generation_v3,
    )

    prd_id = storage.save_artifact(
        run_id="run_v3",
        artifact_type="prd",
        data={
            "prd_id": "prd_test",
            "product_name": "Test App",
            "features": [],
            "acceptance_criteria": [],
        },
    )

    plan = WorkspacePlan(
        app_name="test-app",
        routes=[],
        components=[],
        files=[
            FileSpec(
                path="app/page.tsx",
                kind="route",
                purpose="Main page",
                depends_on=[],
            ),
        ],
        dependencies={},
        acceptance_ids=[],
    )

    async def fake_plan_workspace(
        *,
        prd,
        llm,
    ):
        return plan

    async def fake_generate_batch(
        *,
        prd,
        plan,
        specs,
        workspace,
        llm,
    ):
        return {
            "summary": "Generated route",
            "files": [
                {
                    "path":
                        "app/page.tsx",
                    "content":
                        (
                            "export default "
                            "function Page() {"
                            "return <main>Hello</main>;"
                            "}"
                        ),
                }
            ],
            "_kind": "route",
        }

    monkeypatch.setattr(
        generation_v3,
        "plan_workspace",
        fake_plan_workspace,
    )

    monkeypatch.setattr(
        generation_v3,
        "generate_batch",
        fake_generate_batch,
    )

    output_dir = (
        storage.apps_dir
        / "integration-v3"
    )

    result = await (
        generation_v3
        .generate_nextjs_app_v3(
            prd_id=prd_id,
            output_dir=output_dir,
            llm=object(),
            storage=storage,
        )
    )

    assert (
        output_dir
        / "app/page.tsx"
    ).exists()

    assert (
        "app/page.tsx"
        in result["files"]
    )
```

这条测试应该成为 CI 必跑。

---

# 4. P0-2：Interrupt / Stop 仍然错误地取消整个 Run

这是当前 Continuous Agent 最危险的问题。

现在 PaperForge 的领域模型已经逐渐变成：

```text
Run
=
persistent thread/workspace

Task
=
one user request
```

但是 cancellation 语义仍然停留在旧模型：

```text
Run
=
one execution
```

---

# 5. Interrupt 当前为什么会把下一条请求一起毒死

`api/routes/messages.py`：

```python
if req.mode == "interrupt":
    await _run_queue.cancel_and_wait(
        run_id
    )
```

这本身没问题：

```text
Interrupt
→ cancel current task
```

但是被 cancel 的 Orchestrator 会进入：

```python
except asyncio.CancelledError:
    previous = (
        self.storage
        .get_run_status(run_id)
        or "running"
    )

    self.storage.update_run_status(
        run_id,
        "cancelled",
    )

    self._update_task(
        status="cancelled",
        phase=self.phase.value,
    )

    await emit.run_status_changed(
        "cancelled",
        previous,
    )

    raise
```

于是：

```text
Task A cancelled
↓
整个 Run.status = cancelled
```

新 Interrupt Task B 随后正常创建并 enqueue。

但是 Task B 的 Orchestrator 一启动：

```python
prev_status = (
    self.storage
    .get_run_status(run_id)
    or "active"
)

if (
    prev_status in {"cancelled"}
    or run_row.get("archived_at")
):
    return
```

于是：

```text
Task B
↓
什么都不执行
↓
直接 return
```

这与“Interrupt current task and continue”完全冲突。

---

# 6. Stop 也有同样的问题

当前：

```text
POST /runs/{run_id}/cancel
```

在 cancel 当前 asyncio task 后，又明确：

```python
storage.update_run_status(
    run_id,
    "cancelled"
)
```

而前端按钮语义是：

```text
Stop the current task
```

所以当前存在明确的 UI / Domain Contract mismatch：

```text
UI:
Stop current task

Backend:
Cancel entire thread
```

这必须统一。

---

# 7. 正确的 Cancellation Domain Model

建议明确：

```text
Task.cancel
=
停止当前任务

Run.archive
=
让整个 Thread 不再接受工作

Run.delete
=
删除 Thread
```

不要再保留：

```text
Run.cancelled
=
用户点 Stop
```

这一层永久 terminal 语义。

正确状态变化：

```text
Task A
running
→ cancelled

Run
running
→ active
```

然后：

```text
下一 Task
queued
→ running
```

---

# 8. 推荐新增 Task Cancel API

不要继续把 Stop 挂在：

```text
POST /runs/{run_id}/cancel
```

新增：

```text
POST /runs/{run_id}/tasks/{task_id}/cancel
```

或：

```text
POST /tasks/{task_id}/cancel
```

示例：

```python
@router.post(
    "/{run_id}/tasks/{task_id}/cancel"
)
async def cancel_task(
    run_id: str,
    task_id: str,
) -> dict:
    storage = get_storage()

    task = storage.get_task(
        task_id
    )

    if (
        not task
        or task["run_id"] != run_id
    ):
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    if task["status"] not in {
        "queued",
        "running",
        "waiting_user",
        "waiting_approval",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Task is not cancellable"
            ),
        )

    queue = get_run_queue()

    if task["status"] == "running":
        await queue.cancel_and_wait(
            run_id
        )

    storage.update_task(
        task_id=task_id,
        status="cancelled",
    )

    run = storage.get_run(
        run_id
    )

    previous = (
        run.get("status")
        if run
        else "running"
    )

    storage.update_run_status(
        run_id,
        "active",
    )

    emitter = EventEmitter(
        run_id=run_id,
        manager=get_event_manager(),
        task_id=task_id,
    )

    await emitter.run_status_changed(
        "active",
        previous,
    )

    await emitter.run_updated(
        status="active",
    )

    return {
        "status": "cancelled",
        "task_id": task_id,
        "run_id": run_id,
    }
```

---

# 9. Orchestrator CancelledError 也必须改

当前不能再：

```python
self.storage.update_run_status(
    run_id,
    "cancelled",
)
```

建议：

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

    # Current task stopped.
    # Persistent thread stays usable.
    self.storage.update_run_status(
        run_id,
        "active",
    )

    with contextlib.suppress(
        Exception
    ):
        await emit.run_status_changed(
            "active",
            previous,
        )

        await emit.run_updated(
            status="active",
            phase=self.phase.value,
        )

    raise
```

同时删除 Orchestrator 开头：

```python
if prev_status in {
    "cancelled"
}:
    return
```

真正的 thread-level blocker 只保留：

```python
if run_row.get(
    "archived_at"
):
    return
```

---

# 10. 现有测试还在强化旧 Cancellation 语义

当前 `tests/test_task_cancel.py` 仍然预期：

```text
cancel endpoint
→ Run.status == cancelled
→ cancelled Run 不能 resume
```

这与现在 UI 的：

```text
Stop current task
```

以及“Run = persistent thread”模型冲突。

所以这次不能只改实现，还要**删除/改写旧测试 contract**。

新的测试应该是：

```python
@pytest.mark.asyncio
async def test_stop_cancels_task_but_thread_remains_usable(
    client,
    storage,
    running_task,
):
    run_id = (
        running_task["run_id"]
    )

    response = await client.post(
        (
            f"/api/runs/{run_id}"
            f"/tasks/"
            f"{running_task['id']}"
            "/cancel"
        )
    )

    assert (
        response.status_code
        == 200
    )

    task = storage.get_task(
        running_task["id"]
    )

    assert (
        task["status"]
        == "cancelled"
    )

    run = storage.get_run(
        run_id
    )

    assert (
        run["status"]
        == "active"
    )

    next_response = (
        await client.post(
            f"/api/runs/{run_id}/messages",
            json={
                "content":
                    "Try another approach",
                "mode": "queue",
            },
        )
    )

    assert (
        next_response.status_code
        == 200
    )
```

---

# 11. P0-3：Verification Runtime 完成后没有重新计算 Product Ready

当前 `verify_app()` 已经正确有：

```text
technical_ready
preview_allowed
product_ready
```

这比早期版本已经好很多。

但是初次 verification 时：

```text
runtime_ok = None
```

因此：

```text
product_ready = False
```

这是合理的。

随后 Sandbox 启动成功后：

```python
_finalize_verification_runtime(...)
```

会更新：

```text
runtime layer
runtime_status
browser_smoke
acceptance layer
acceptance_status
```

但当前没有重新更新：

```text
report["gates"]["runtime_ok"]
report["gates"]["acceptance_ok"]

report["technical_ready"]
report["preview_allowed"]
report["product_ready"]
```

所以会出现：

```text
Build             ✓
Typecheck         ✓
Runtime Preview   ✓
Acceptance        ✓

product_ready     False
```

最终状态没有闭环。

---

# 12. Readiness 必须只有一个计算函数

不要在：

```text
verifier.py
tools.py runtime finalizer
build_and_repair
```

分别计算。

新增：

```python
def recompute_readiness(
    report: dict[str, Any],
) -> dict[str, Any]:
    gates = report.setdefault(
        "gates",
        {},
    )

    technical_ready = all(
        gates.get(key) is True
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

    # Backward-compat only.
    report[
        "ready_for_preview"
    ] = preview_allowed

    return report
```

---

# 13. Runtime Finalizer 正确写法

```python
gates = report.setdefault(
    "gates",
    {},
)

gates["runtime_ok"] = (
    runtime_ok
)

if acceptance_status == "passed":
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

updated = (
    ctx.storage.update_artifact(
        artifact["id"],
        data=report,
    )
)
```

这之后，正常完整 pipeline 才有机会真正达到：

```text
product_ready = True
```

---

# 14. P1：RunTaskManager 的 replacement callback 有竞态

当前：

```python
existing = self.tasks.get(
    run_id
)

if (
    existing
    and not existing.done()
):
    existing.cancel()

task = asyncio.create_task(
    coro
)

self.tasks[run_id] = task

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
Task A 在 manager
↓
start Task B
↓
A.cancel()
↓
manager[run] = B
↓
A 的 done callback 稍后执行
↓
pop(run_id)
↓
把 B 从 manager 删掉
```

然后：

```text
is_running(run_id) = false
```

但 B 其实仍然在执行。

这会严重影响：

```text
interrupt
stop
queue scheduling
```

---

# 15. 修复 Manager Callback

```python
def start(
    self,
    run_id: str,
    coro: Coroutine,
) -> asyncio.Task:
    existing = self.tasks.get(
        run_id
    )

    if (
        existing
        and not existing.done()
    ):
        existing.cancel()

    task = asyncio.create_task(
        coro
    )

    self.tasks[
        run_id
    ] = task

    def cleanup(
        done: asyncio.Task,
    ) -> None:
        # Only remove ourselves.
        if (
            self.tasks.get(run_id)
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

最好进一步把 API 分成：

```text
start_if_idle()
replace_after_cancel()
```

避免普通 scheduler 随意 replace 当前任务。

---

# 16. P1：RunQueue Worker 有 empty-queue race

当前：

```python
while (
    queue is not None
    and not queue.empty()
):
    task_id = await queue.get()
    ...
finally:
    self._queues.pop(
        run_id,
        None
    )
    self._workers.pop(
        run_id,
        None
    )
```

竞态：

```text
Worker 判断 queue.empty() == True

               ← 此时 enqueue 新 Task B
enqueue 看到旧 worker 还没 done
所以不创建新 worker

旧 worker 进入 finally
pop queue

Task B 被留在刚刚被 pop 的 Queue object
没有 worker
```

数据库 Task B 仍 queued，但要等：

```text
下一次 enqueue
或 server restart
```

才会再次被处理。

---

# 17. 最小修复 Queue Worker Race

可以用 per-run lock；更推荐 worker 退出时再 recheck：

```python
async def _worker(
    self,
    run_id: str,
) -> None:
    storage = (
        self._storage
        or _default_storage()
    )

    try:
        while True:
            queue = self._queues.get(
                run_id
            )

            if queue is None:
                return

            try:
                task_id = (
                    await asyncio.wait_for(
                        queue.get(),
                        timeout=0.25,
                    )
                )
            except asyncio.TimeoutError:
                # Double-check DB and queue
                # before retiring.
                if (
                    queue.empty()
                    and not (
                        storage
                        .get_next_queued_task(
                            run_id
                        )
                    )
                ):
                    return

                continue

            try:
                await self._claim_and_run(
                    run_id,
                    task_id,
                    storage,
                )
            finally:
                queue.task_done()

    finally:
        current = (
            self._workers.get(
                run_id
            )
        )

        if (
            current
            is asyncio.current_task()
        ):
            self._workers.pop(
                run_id,
                None
            )

        queue = self._queues.get(
            run_id
        )

        if (
            queue is not None
            and not queue.empty()
        ):
            self._workers[
                run_id
            ] = asyncio.create_task(
                self._worker(
                    run_id
                )
            )
        else:
            self._queues.pop(
                run_id,
                None
            )
```

更长期仍建议：

```text
DB scheduler
+
per-run serialization
```

而不是让 in-memory queue 自己承担 durable scheduling correctness。


# 18. P1：Claim 失败后不能盲目把 Task 改回 queued

当前 worker：

```python
executed = await (
    self._claim_and_run(
        run_id,
        task_id,
        storage,
    )
)

if (
    not executed
    and storage is not None
):
    storage.update_task(
        task_id=task_id,
        status="queued",
    )
```

这是单进程下看起来合理，但多 worker 下危险。

场景：

```text
Worker A
和 Worker B
都恢复到了同一个 queued task

A claim 成功
DB.status = running

B claim 失败
↓
B 当前代码：
status = queued

于是 A 正在执行的 Task
被 B 重新写回 queued
```

接下来另一个 worker 又能 claim，造成 duplicate execution。

## 修复原则

**Claim 失败不是 Requeue 信号。**

Claim 失败后应该检查当前状态：

```python
if not executed:
    row = storage.get_task(
        task_id
    )

    if not row:
        continue

    status = row.get(
        "status"
    )

    if status == "queued":
        # 仍是 queued 才考虑重新触发。
        await self.enqueue(
            run_id,
            task_id,
        )

    elif status == "running":
        # Another worker owns it.
        pass

    elif status in {
        "completed",
        "failed",
        "cancelled",
    }:
        pass
```

更好的设计是 `_claim_and_run()` 返回 typed outcome：

```python
class ClaimOutcome(
    str,
    Enum,
):
    EXECUTED = "executed"
    CLAIMED_BY_OTHER = (
        "claimed_by_other"
    )
    ALREADY_TERMINAL = (
        "already_terminal"
    )
    INVALID = "invalid"
```

然后 scheduler 只根据明确结果行动。

---

# 19. P1：Queue 不应在 finally 中“猜测任务完成”

当前：

```python
row = storage.get_task(
    task_id
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

这意味着：

> 只要 Orchestrator coroutine 返回，而 Task row 还停在 running，Queue 就认为它成功了。

但 Orchestrator 可能因为：

```text
run archived
run cancelled
early return
future guard
逻辑 Bug
unexpected branch
```

提前 return。

Scheduler 不应该推断业务完成。

## 正确设计

Orchestrator 自己返回一个 outcome：

```python
class OrchestratorOutcome(
    BaseModel
):
    task_id: str | None
    status: Literal[
        "completed",
        "waiting_user",
        "failed",
        "cancelled",
    ]
    phase: str
    summary: str | None = None
```

例如：

```python
async def run(
    ...
) -> OrchestratorOutcome:
    ...
```

Queue：

```python
outcome = await asyncio.shield(
    run_task
)

if outcome is None:
    raise RuntimeError(
        "Orchestrator exited "
        "without task outcome"
    )

row = storage.get_task(
    task_id
)

if (
    row
    and row["status"]
       == "running"
):
    storage.update_task(
        task_id=task_id,
        status="failed",
    )

    logger.error(
        "Task %s exited while "
        "still marked running",
        task_id,
    )
```

也就是说：

```text
残留 running
应该 fail loudly
而不是 completed silently
```

---

# 20. P1：Lease 丢失没有真正停止旧 Worker

当前 heartbeat：

```python
ok = storage.renew_task_lease(
    ...
)

if not ok:
    # We lost the lease
    return
```

但 `return` 只结束 heartbeat coroutine。

真正运行的：

```text
Orchestrator Task
```

仍然继续。

多 worker 情况：

```text
Worker A 正在修改 workspace

A lease renewal 失败
↓
A heartbeat 停止
↓
A Orchestrator 继续运行

lease expires
↓
Worker B reclaim
↓
B Orchestrator 也开始运行
```

于是两个 Agent 同时：

```text
patch workspace
build
repair
write revisions
```

这是 production concurrency hazard。

---

# 21. Lease Loss 应该变成 Cancellation Signal

```python
class LeaseLostError(
    RuntimeError
):
    pass
```

Heartbeat：

```python
async def _heartbeat(
    self,
    task_id: str,
    worker_id: str,
    *,
    interval: int,
    lease_seconds: int,
    storage,
    lease_lost:
        asyncio.Event,
) -> None:
    while True:
        await asyncio.sleep(
            interval
        )

        lease_until = (
            datetime.utcnow()
            + timedelta(
                seconds=(
                    lease_seconds
                )
            )
        ).isoformat()

        ok = storage.renew_task_lease(
            task_id=task_id,
            worker_id=worker_id,
            lease_until=lease_until,
        )

        if not ok:
            lease_lost.set()
            return
```

运行：

```python
lease_lost = asyncio.Event()

heartbeat = asyncio.create_task(
    self._heartbeat(
        ...,
        lease_lost=lease_lost,
    )
)

run_task = self._manager.start(
    run_id,
    coro,
)

lease_waiter = asyncio.create_task(
    lease_lost.wait()
)

done, pending = (
    await asyncio.wait(
        {
            run_task,
            lease_waiter,
        },
        return_when=(
            asyncio.FIRST_COMPLETED
        ),
    )
)

if (
    lease_waiter in done
    and lease_lost.is_set()
):
    if not run_task.done():
        run_task.cancel()

        with suppress(
            asyncio.CancelledError
        ):
            await run_task

    raise LeaseLostError(
        f"Lost lease for "
        f"{task_id}"
    )
```

同时：

```text
lease loss
≠
Task user-cancelled
```

应该让状态变成：

```text
queued / failed-retryable
```

由 scheduler 决定重试。

---

# 22. P1：Generation V3 仍缺严格的 Batch Contract

现在 V3 架构方向已经是正确的：

```text
PRD
→ WorkspacePlan
→ group by kind
→ generate_batch
→ write files
```

但是 `generate_batch()` 当前：

```python
data = json.loads(
    response.content
    or "{}"
)

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

没有强 schema。

`write_batch_files()` 也只做：

```text
不能逃出 workspace root
```

没有验证：

```text
是不是 WorkspacePlan 里的文件
是不是允许的 root
是不是 protected config
文件是否超大
batch 总量是否超限
```

所以模型可能在：

```text
component batch
```

返回：

```text
package.json
next.config.js
.env
```

只要仍在 app root 里面，就可能被写。

---

# 23. Generation V3 应使用 Typed Batch Output

```python
from pydantic import (
    BaseModel,
    Field,
    model_validator,
)


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

`generate_batch()`：

```python
async def generate_batch(
    *,
    prd: dict,
    plan: WorkspacePlan,
    specs: list[FileSpec],
    workspace: Path,
    llm: LLMClient,
) -> GeneratedBatch:
    ...

    raw = json.loads(
        response.content
        or "{}"
    )

    batch = (
        GeneratedBatch
        .model_validate(
            raw
        )
    )

    validate_batch_contract(
        specs=specs,
        batch=batch,
    )

    return batch
```

---

# 24. Batch 必须严格匹配 WorkspacePlan

```python
def validate_batch_contract(
    *,
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

    missing = (
        expected - actual
    )

    unexpected = (
        actual - expected
    )

    if missing:
        raise ValueError(
            "Generation batch "
            "omitted planned files: "
            + ", ".join(
                sorted(missing)
            )
        )

    if unexpected:
        raise ValueError(
            "Generation batch "
            "returned unplanned files: "
            + ", ".join(
                sorted(unexpected)
            )
        )

    if (
        len(actual)
        != len(batch.files)
    ):
        raise ValueError(
            "Generation batch "
            "contains duplicate paths"
        )
```

这样：

```text
WorkspacePlan
```

才真正是代码生成 contract，而不是仅用于 prompt context。

---

# 25. V3 写文件也必须复用 SafeWorkspacePolicy

不要让：

```text
Agent patch
```

走严格 policy，而：

```text
initial generation
```

走宽松 writer。

统一：

```python
def write_batch_files(
    *,
    workspace: Path,
    batch: GeneratedBatch,
    policy:
        SafeWorkspacePolicy
        | None = None,
) -> list[str]:
    policy = (
        policy
        or SafeWorkspacePolicy()
    )

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
            "Generated batch "
            "exceeds size limit"
        )

    changed: list[str] = []

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

# 26. V3 Atomic Promotion 还有 Crash Window

当前大致是：

```python
if final_dir.exists():
    os.replace(
        final_dir,
        backup,
    )

os.replace(
    temp_dir,
    final_dir,
)
```

如果：

```text
final_dir → backup
```

成功，但下一句：

```text
temp_dir → final_dir
```

失败或进程崩溃：

```text
final_dir 不存在
workspace 看起来消失
```

虽然 `.previous` 还在，但没有自动恢复。

## 修复

```python
backup: Path | None = None

try:
    if final_dir.exists():
        backup = (
            final_dir.with_name(
                final_dir.name
                + ".previous"
            )
        )

        if backup.exists():
            shutil.rmtree(
                backup
            )

        os.replace(
            final_dir,
            backup,
        )

    os.replace(
        temp_dir,
        final_dir,
    )

except Exception:
    if (
        backup is not None
        and backup.exists()
        and not final_dir.exists()
    ):
        os.replace(
            backup,
            final_dir,
        )

    raise
```

完成后再根据保留策略决定是否保留 `.previous`。

---

# 27. P1：Approval task_id 在 Hydration 中仍然丢失

数据库现在已经存：

```text
approvals.task_id
```

但 `api/routes/runs.py` 的 serializer：

```python
def _to_approval(
    row,
):
    return {
        "approval_id":
            row["id"],
        "run_id":
            row["run_id"],
        "tool":
            row["tool_name"],
        "args":
            row.get("args")
            or {},
        "status":
            row["status"],
        ...
    }
```

没有：

```text
task_id
```

所以：

```text
实时阶段
也许知道 task_id

刷新页面
↓
/state hydration
↓
approval.task_id 丢失
↓
Turn Projection 无法归属
```

## 修复

```python
def _to_approval(
    row: dict[str, Any],
) -> dict[str, Any]:
    return {
        "approval_id":
            row["id"],

        "run_id":
            row["run_id"],

        "task_id":
            row.get(
                "task_id"
            ),

        "tool":
            row["tool_name"],

        "tool_name":
            row["tool_name"],

        "args":
            row.get("args")
            or {},

        "status":
            row["status"],

        "created_at":
            row["created_at"],

        "resolved_at":
            row.get(
                "resolved_at"
            ),
    }
```

---

# 28. Realtime Approval 也计算了 taskId，却没有使用

`run-events.ts` 已经统一计算：

```typescript
const taskId =
  data.task_id
  ?? data.taskId
  ?? event.task_id
  ?? undefined;
```

但：

```typescript
case "approval.requested":
  store.addPendingApproval({
    ...
    task_id:
      data.task_id,
  });
```

这里没有用已经计算好的：

```text
taskId
```

直接改：

```typescript
case "approval.requested":
  store.addPendingApproval({
    approval_id:
      data.approval_id,

    id:
      data.approval_id,

    run_id:
      runId,

    task_id:
      taskId,

    tool:
      data.tool
      || data.tool_name
      || "",

    tool_name:
      data.tool_name
      || data.tool
      || "",

    args:
      data.args
      || {},

    status:
      "pending",

    created_at:
      data.created_at
      || undefined,
  });

  return "applied";
```

---

# 29. P1：Turn 顺序可能是 newest-first

Storage：

```sql
SELECT *
FROM tasks
WHERE run_id = ?
ORDER BY created_at DESC
```

而 `projectTurns()`：

```typescript
for (
  const task
  of tasks
) {
    ...
    turns.push(...)
}
```

没有排序。

如果 `/state` 直接把 Storage list 塞给前端，Chat 可能变成：

```text
Turn 3
Turn 2
Turn 1
```

而正常 conversation 应该：

```text
Turn 1
Turn 2
Turn 3
```

## 推荐在 API 层明确 timeline 顺序

对于 conversation state：

```sql
ORDER BY
    created_at ASC,
    id ASC
```

如果其它管理界面需要 newest-first，单独 endpoint。

也可以前端保险：

```typescript
const orderedTasks = [
  ...tasks
].sort(
  (left, right) => {
    const l = Date.parse(
      left.created_at
      ?? "1970-01-01"
    );

    const r = Date.parse(
      right.created_at
      ?? "1970-01-01"
    );

    return l - r;
  }
);
```

然后 projection。

---

# 30. P1：Verifier Streaming Checks 丢弃 exit code

现在 process runner 本身已经做对：

```python
return (
    result.returncode == 0
    and not result.timed_out,
    result.stdout,
)
```

但是 `_run_checks_streaming()`：

```python
for cmd in (
    tsc,
    lint,
):
    _, _ = await (
        _exec_streaming(
            ...
        )
    )

return (
    len(errors) == 0,
    errors,
)
```

也就是说 `ok` 被扔掉。

因此：

```text
command exit code = 1
```

只要日志里没有：

```text
"error"
"failed"
```

就可能返回：

```text
ok = True
```

这是 correctness bug。

---

# 31. 修复 Streaming Check

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

    async def cb(
        text: str,
    ) -> None:
        line = text.strip()

        if not line:
            return

        await progress.progress(
            step_id,
            detail=line[:400],
        )

        if (
            "error"
            in line.lower()
            or "failed"
               in line.lower()
        ):
            errors.append(
                line
            )

    all_ok = True

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
            await _exec_streaming(
                cmd,
                app_path,
                timeout,
                cb,
            )
        )

        all_ok = (
            all_ok and ok
        )

        if (
            not ok
            and not any(
                token in output.lower()
                for token
                in (
                    "error",
                    "failed",
                )
            )
        ):
            errors.append(
                (
                    f"Command failed "
                    f"with non-zero "
                    f"exit status: "
                    f"{' '.join(cmd)}"
                )
            )

    return (
        all_ok
        and len(errors) == 0,
        errors,
    )
```

---

# 32. P1：Browser Acceptance Upload 可读取任意本地路径

当前：

```python
elif action == "upload":
    if input_value is None:
        raise RuntimeError(
            "upload action requires "
            "a fixture path."
        )

    await locator.set_input_files(
        str(input_value)
    )
```

`input_value` 来自：

```text
PRD / LLM generated criterion
```

因此模型可以指定：

```text
/etc/passwd
/home/.../.env
repo 内其它文件
```

只要 Browser Smoke Python process 有读取权限，Playwright 就可能读。

这不应该允许。

---

# 33. 推荐只支持受控 Fixture

最安全方式是不让 LLM 选择真实 filesystem path。

例如 schema：

```text
fixture:
text
small_pdf
csv
image
```

Executor：

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
            b"name,value\n"
            b"sample,1\n",
    },
}
```

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
            "Unknown browser "
            "test fixture"
        )

    await locator.set_input_files(
        fixture
    )
```

如果一定要 filesystem：

```python
fixture_root = (
    output_dir
    / "fixtures"
).resolve()

candidate = (
    fixture_root
    / str(input_value)
).resolve()

candidate.relative_to(
    fixture_root
)
```

绝对不能直接信任任意路径。

---

# 34. P1：`verify_app` Resource Gate 定义不准确

当前：

```python
"verify_app": ToolSpec(
    name="verify_app",

    requires_any=(
        frozenset({
            "workspace"
        }),
        frozenset({
            "prd"
        }),
    ),
)
```

语义是：

```text
有 workspace
OR
有 PRD
```

就可以调用 verifier。

但是 handler 一开始：

```python
app_path = (
    _resolve_app_path(
        args,
        ctx,
    )
)
```

所以没有 workspace 的：

```text
PRD-only
```

状态实际上不能 verify。

## 改成

```python
"verify_app": ToolSpec(
    name="verify_app",

    requires=frozenset({
        "workspace",
    }),

    produces=frozenset({
        "verification",
    }),

    risk="sandbox_exec",
)
```

PRD 是：

```text
optional context
```

不是 prerequisite alternative。

同理建议检查所有 ToolSpec：

```text
resource contract
```

是否与 handler 第一行的真实依赖一致。

---

# 35. P1：Workspace 改变后 Editor Tabs 仍保留旧内容

当前 `PreviewPanel.tsx` 已经从超大 God Component 拆到约 212 行，这一点是明显进步。

但是：

```typescript
useEffect(
  () => {
    if (
      appArtifactId
    ) {
      api.listAppTree(...)
      ...
    }
  },
  [
    appArtifactId,
    currentRun?.id,
    sandbox?.id,
  ],
);
```

`appArtifactId` 改变时刷新了：

```text
tree
```

但没有：

```typescript
setTabs([]);
setActiveTabPath(null);
```

场景：

```text
Workspace A
打开 app/page.tsx
tab 中有旧内容

Agent regenerate
→ Workspace B / appArtifactId change

Tree 切到了 B
但旧 editor tab 仍是 A 的内容

用户点 Save
↓
API 现在对 B 保存旧 tab 内容
```

这是数据一致性问题。

---

# 36. Workspace Identity Change 时清理/重验证 Tabs

简单方案：

```typescript
const previousAppId =
  useRef<
    string | undefined
  >(
    appArtifactId
  );

useEffect(
  () => {
    if (
      previousAppId.current
      && previousAppId.current
         !== appArtifactId
    ) {
      setTabs([]);
      setActiveTabPath(
        null
      );
    }

    previousAppId.current =
      appArtifactId;
  },
  [
    appArtifactId,
  ],
);
```

如果有 dirty tab，最好先：

```text
Workspace changed.
Unsaved local editor changes were discarded.
```

或禁止 regeneration 前有 dirty tab。

更强方案是 `EditorTab` 记录：

```typescript
interface EditorTab {
  workspaceId: string;
  path: string;
  ...
}
```

保存前：

```typescript
if (
  tab.workspaceId
  !== appArtifactId
) {
  throw new Error(
    "This tab belongs to "
    "an older workspace revision."
  );
}
```

---

# 37. P1：Open in New Tab 绕过 isolated preview URL

当前 iframe 已经正确：

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

这是对的。

但是：

```typescript
const handleOpenNewTab =
  () => {
    if (sandbox?.id) {
      window.open(
        api.getPreviewUrl(
          sandbox.id
        ),
        "_blank"
      );
    }
  };
```

又回到了：

```text
/api/preview/...
```

production 的独立 preview origin 被绕开。

修：

```typescript
const handleOpenNewTab =
  () => {
    if (!previewSrc) {
      return;
    }

    window.open(
      previewSrc,
      "_blank",
      "noopener,noreferrer",
    );
  };
```

---

# 38. P1：`run-events.ts` 的 Result 名称仍可进一步收口

当前：

```typescript
export type ApplyRunEventResult =
  | "applied"
  | "duplicate"
  | "gap"
  | "unknown";
```

而现在 unknown event 的真实语义已经是：

```text
合法收到
seq 已推进
客户端暂时不处理
```

它其实不是 unknown-error。

建议改为：

```typescript
export type ApplyRunEventResult =
  | "applied"
  | "ignored"
  | "duplicate"
  | "gap";
```

Default：

```typescript
default:
  return "ignored";
```

这样未来阅读：

```text
ignored
≠
gap
```

更清晰。

这不是功能 blocker，但可以作为 protocol cleanup。


# 39. P2：Parser 仍然不是 Whole-Paper Understanding

当前 Parser 已经做了一个正确的改进：

```text
如果没有完整处理论文
→ ParseCoverage 明确告诉 UI
```

所以现在不会再静默把：

```text
“前 16 个 chunk 的理解”
```

伪装成：

```text
“整篇论文理解”
```

但是实现仍然：

```python
MAX_CHUNKS = 32
MAX_MAP_CHUNKS = 16
```

Chunk 数超过：

```python
MAX_CHUNKS
```

会：

```python
chunks = chunks[
    :max_chunks
]
```

Map 阶段达到：

```python
MAX_MAP_CHUNKS
```

会直接：

```python
break
```

所以当前能力准确描述应该是：

```text
Bounded Partial Paper Understanding
```

而不是：

```text
Whole-Paper Understanding
```

---

# 40. Parser 当前还有一个 ParseCoverage 计算 Bug

当前 map 成功结果记录：

```python
mapped.append({
    "chunk": index,
    "data": chunk_data,
})
```

如果某个 chunk JSON 解析失败：

```python
continue
```

说明 mapped 可能是：

```text
chunk 1 success
chunk 2 failed
chunk 3 success
```

最终：

```python
len(mapped) == 2
```

但 coverage 当前：

```python
processed_chunks = (
    chunks[
        :min(
            len(mapped),
            MAX_MAP_CHUNKS,
        )
    ]
)
```

也就是认为：

```text
chunk 1
chunk 2
```

被成功处理。

实际上应该是：

```text
chunk 1
chunk 3
```

这会让：

```text
processed_pages
omitted_pages
```

出现错误。

---

# 41. 修复 ParseCoverage

按 mapped 中真实 index 恢复：

```python
processed_chunks: list[str] = []

for item in mapped:
    raw_index = item.get(
        "chunk"
    )

    try:
        index = int(
            raw_index
        )
    except (
        TypeError,
        ValueError,
    ):
        continue

    # mapped currently uses 1-based index.
    position = index - 1

    if (
        0
        <= position
        < len(chunks)
    ):
        processed_chunks.append(
            chunks[position]
        )

coverage = (
    _build_parse_coverage(
        pages,
        processed_chunks,
    )
    .model_dump()
)
```

更好的做法是 map stage 不存裸 `chunk` integer，而是：

```python
{
    "chunk_id":
        "chunk_0003",
    "chunk_index":
        2,
    "page_numbers":
        [7, 8, 9],
    "data":
        {...},
}
```

Coverage 就无需二次从字符串 marker 猜测。

---

# 42. Whole-Paper Parser 最终方案

不要把预算控制理解成：

```text
只看前 16 chunks
```

应该：

```text
全部 chunks
↓
map
↓
分组 reduce
↓
再 reduce
↓
final capability synthesis
```

例如：

```python
async def hierarchical_reduce(
    *,
    mapped:
        list[ChunkMap],
    llm: LLMClient,
    group_size: int = 6,
) -> list[dict]:
    level = [
        item.model_dump()
        for item in mapped
    ]

    while (
        len(level)
        > group_size
    ):
        next_level = []

        for offset in range(
            0,
            len(level),
            group_size,
        ):
            group = level[
                offset:
                offset + group_size
            ]

            summary = (
                await reduce_group(
                    group=group,
                    llm=llm,
                )
            )

            next_level.append(
                summary
            )

        level = next_level

    return level
```

最终：

```python
final = await (
    synthesize_capability(
        summaries=level,
        llm=llm,
    )
)
```

这样预算复杂度由：

```text
每层 bounded
```

控制，而不是直接丢论文后半段。

---

# 43. P2：CapabilityContract 仍没有进入 Runtime

当前已经有：

```text
CapabilityContract schema
ParseCoverage schema
```

但 `paper_parser.py` 最终仍：

```python
CapabilityCard.model_validate(
    card
)
```

Tool 也仍然保存：

```text
artifact_type =
capability_card
```

所以：

```text
CapabilityContract schema exists
```

不等于：

```text
Product Planner uses CapabilityContract
```

---

# 44. 建议把 Card 与 Contract 分开

```text
CapabilityCard
=
给用户看的论文能力摘要

CapabilityContract
=
给 Planner / Generator 使用的可执行能力契约
```

Parser 最终 artifact：

```json
{
  "paper_id": "paper_x",
  "card": {
    "...": "..."
  },
  "contract": {
    "inputs": [],
    "outputs": [],
    "preconditions": [],
    "failure_modes": [],
    "compute_requirements": [],
    "integration_mode": "unknown",
    "implementation_refs": [],
    "confidence": 0.83
  },
  "parse_coverage": {
    "total_pages": 22,
    "processed_pages": [1, 2, 3],
    "omitted_pages": [],
    "complete": true
  }
}
```

Planner：

```python
contract = (
    capability_artifact
    .get("data", {})
    .get("contract")
)

if contract:
    planner_context[
        "capability_contract"
    ] = contract
```

这会比仅凭 free-text capability card 更适合：

```text
Mock vs Real integration
模型依赖
输入输出 contract
失败模式
产品边界
```

---

# 45. P2：OpenAPI Schema 已生成，但 Contract 仍有重复

现在 repo 已经生成：

```text
web/lib/api/schema.d.ts
```

这是正确的。

但是 `web/lib/api.ts` 仍然从：

```typescript
"./store"
```

导入很多：

```text
Run
Message
Paper
Sandbox
Event
Approval
Artifact
```

部分函数仍：

```text
Promise<any>
Record<string, any>
```

Realtime 也有：

```text
api.ts RunEvent
contracts.ts RunEventEnvelope
store.ts Event
```

多个相似 type。

风险：

```text
backend schema 改
↓
generated type 已更新
↓
但真正调用层仍在用旧手写类型
```

---

# 46. 建议 Type Boundary

最终只保留三层：

```text
1. HTTP API Contract
   = generated OpenAPI

2. Realtime Protocol
   = RunEvent discriminated union

3. UI Projection
   = Zustand / ConversationTurn
```

目录：

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

---

# 47. API Type 示例

```typescript
import type {
  components,
} from "./schema";

export type ApiRun =
  components[
    "schemas"
  ][
    "Run"
  ];

export type ApiTask =
  components[
    "schemas"
  ][
    "Task"
  ];

export type ApiMessage =
  components[
    "schemas"
  ][
    "Message"
  ];
```

然后 `client.ts`：

```typescript
export async function getRunState(
  runId: string,
): Promise<RunStateResponse> {
  return request<
    RunStateResponse
  >(
    `/api/runs/${runId}/state`
  );
}
```

而不是：

```typescript
Promise<any>
```

---

# 48. P2：Default EventBroker 仍然只是 In-Process

当前这部分已经比上一轮好：

```text
EventManager
→ EventStore
→ EventBroker
```

不再是纯 scaffold。

这应该保留。

但是默认 Broker 仍然：

```text
InProcessEventBroker
```

所以如果未来部署：

```text
uvicorn workers=4
```

可能出现：

```text
Worker A
执行 Orchestrator

Worker B
持有用户 SSE connection
```

两者没有共享 live broker。

DB replay 可以在 reconnect 后恢复，但不是实时。

---

# 49. Production Broker 不需要现在就过度设计

等真正上多 worker 时实现：

```python
class RedisEventBroker(
    EventBroker
):
    async def publish(
        self,
        event: Event,
    ) -> None:
        await self.redis.publish(
            f"paperforge:"
            f"run:{event.run_id}",
            event.model_dump_json(),
        )

    async def subscribe(
        self,
        run_id: str,
    ):
        pubsub = (
            self.redis.pubsub()
        )

        await pubsub.subscribe(
            f"paperforge:"
            f"run:{run_id}"
        )

        try:
            async for raw in (
                pubsub.listen()
            ):
                if (
                    raw.get("type")
                    != "message"
                ):
                    continue

                yield (
                    Event
                    .model_validate_json(
                        raw["data"]
                    )
                )

        finally:
            await pubsub.unsubscribe(
                f"paperforge:"
                f"run:{run_id}"
            )
```

现在不必为了未来多 worker 再重构 Event domain。

---

# 50. Broker Queue Full 应至少可观测

InProcess Broker 如果 queue full 时只：

```text
drop
```

理论上后续 seq gap 可以触发 snapshot hydration。

功能可恢复。

但 production 应记录：

```text
broker_live_drop_total
```

例如：

```python
try:
    queue.put_nowait(
        event
    )
except asyncio.QueueFull:
    metrics.increment(
        "broker_live_drop_total",
        tags={
            "run_id":
                event.run_id
        },
    )
```

否则只能看到用户偶尔 hydrate，不知道 Broker backpressure 已经异常。

---

# 51. 现在测试体系最大的缺口不是“测试数量少”

当前 tests 已经不少。

问题是：

> **很多测试验证的是模块，而不是主链契约。**

当前典型情况：

```text
Generation V3 helpers test      ✓
Generation V3 wiring test       ✓
Generation V3 real execution    ✗

Queue priority test             ✓
Interrupt continuation test     ✗

Task cancel terminal test       ✓
Persistent-thread cancel model  ✗

Worker lease storage test       ✓
Lease loss stops execution      ✗

Run state contract test         ✓
Approval task attribution       ✗
```

---

# 52. 当前所谓 Full Pipeline Test 并不是真正 Full Pipeline

现有：

```text
tests/e2e/test_full_pipeline.py
```

名称很像：

```text
Paper
→ Parse
→ Plan
→ Generate
→ Verify
→ Preview
```

但当前 fake LLM 路径并没有真正完整跑：

```text
Generation V3
Node build
Sandbox
Browser acceptance
```

所以 `write_batch_files(root=...)` 这种真实主链问题才能留到现在。

建议把测试重新分级。

---

# 53. 测试分层建议

## Level 1 — Unit

```text
helper
schema
policy
parser marker
reducer
```

快速。

## Level 2 — Domain Contract

```text
Task cancel semantics
Task ID
Resource Gate
Readiness recompute
Batch path contract
```

无 Docker。

## Level 3 — Integration

```text
真实 Storage
fake LLM
真实 Orchestrator
真实 Generation V3 temp workspace
fake process runner
```

重点测试：

```text
模块接线
```

## Level 4 — System E2E

```text
FastAPI
Next frontend
real SSE
fake deterministic provider
sandbox optionally mocked
```

## Level 5 — Docker smoke

只在 nightly / pre-release：

```text
生成最小 App
npm install/build
Docker start
Browser smoke
```

---

# 54. 必须新增的 14 条 Integration Tests

## 54.1 V3 Full Execution

```text
plan
→ batch
→ safe write
→ dependency merge
→ atomic promote
```

必须真正跑。

## 54.2 Interrupt Continuation

```text
Task A running
→ Interrupt Task B
→ A cancelled
→ Run active
→ B running/completed
```

## 54.3 Stop Then Follow-up

```text
Task A running
→ Stop
→ A cancelled
→ later Task C still works
```

## 54.4 Manager Callback Identity Race

```text
A replaced by B
→ A callback fires
→ manager still holds B
```

测试：

```python
@pytest.mark.asyncio
async def test_old_task_callback_cannot_remove_replacement():
    manager = (
        RunTaskManager()
    )

    started = (
        asyncio.Event()
    )

    async def old():
        try:
            await asyncio.sleep(
                100
            )
        finally:
            started.set()

    async def new():
        await asyncio.sleep(
            0.1
        )

    manager.start(
        "run_1",
        old(),
    )

    replacement = (
        manager.start(
            "run_1",
            new(),
        )
    )

    await started.wait()
    await asyncio.sleep(0)

    assert (
        manager.tasks.get(
            "run_1"
        )
        is replacement
    )
```

## 54.5 Enqueue During Worker Shutdown

构造：

```text
queue becomes empty
→ enqueue before finally
→ task still runs
```

## 54.6 Multi-worker Claim Loser

```text
Worker A claims
Worker B fails claim
→ B must not revert status to queued
```

## 54.7 Lease Lost

```text
renew returns false
→ active execution is cancelled
→ never continues patching
```

## 54.8 Runtime Readiness Closure

```text
initial verify:
product_ready=false

runtime success
acceptance success

final report:
product_ready=true
```

## 54.9 Approval Hydration

```text
Approval.task_id
→ DB
→ /state
→ frontend
→ correct Turn
```

## 54.10 Turn Chronological Ordering

```text
Task 1
Task 2
Task 3

UI order:
1,2,3
```

## 54.11 V3 Rejects Unplanned File

模型返回：

```text
.env
```

但 plan 没有。

必须 fail。

## 54.12 Browser Upload Fixture Safety

PRD 尝试：

```text
/etc/passwd
```

必须 fail，而不是读取。

## 54.13 Verifier Nonzero Exit

Command：

```text
exit 1
stdout = "Something went wrong"
```

没有 “error” 关键字。

仍必须：

```text
ok=false
```

## 54.14 Parser Coverage Actual Maps

```text
chunk 1 success
chunk 2 invalid JSON
chunk 3 success
```

Coverage 必须使用：

```text
1 + 3
```

而不是：

```text
1 + 2
```

---

# 55. 推荐 PR 顺序重新调整

基于 2026-08-13 当前代码，不再沿用前几份文档的旧 PR 顺序。

## PR-1 — Main Path Immediate Fixes

只修三个最关键问题：

```text
Generation V3 root/workspace keyword
Task-level Stop/Interrupt semantics
Verification runtime recompute
```

同时加三条 integration tests。

目标：

```text
“最核心主链先能正确跑到底”
```

---

## PR-2 — Queue Concurrency Hardening

修：

```text
RunTaskManager callback identity
worker empty-queue race
claim failure no blind requeue
remove implicit completed inference
lease-loss cancellation
```

目标：

```text
“单机并发不会丢任务，
未来多 worker 不会 duplicate execution”
```

---

## PR-3 — Generation V3 Contract Hardening

修：

```text
GeneratedBatch Pydantic
planned paths exact match
SafeWorkspacePolicy
per-batch size
protected files
atomic promotion rollback
```

目标：

```text
“V3 不只是能跑，而且输出 contract 可控”
```

---

## PR-4 — Turn / Hydration Closure

修：

```text
approval serializer task_id
approval realtime taskId
task chronological ordering
legacy untracked assertions
```

目标：

```text
刷新前后 Turn 不变
```

---

## PR-5 — Verification / Browser Correctness

修：

```text
streaming command exit code
browser upload controlled fixture
verify_app workspace requirement
```

目标：

```text
Verifier 不再产生 false pass
Browser test 不扩大本机文件访问能力
```

---

## PR-6 — Workbench State Safety

修：

```text
workspace identity → reset/revalidate tabs
open-new-tab uses previewSrc
dirty tab workspace guard
```

目标：

```text
不会把旧 Workspace tab 写进新 Workspace
```

---

## PR-7 — Parser V2

修：

```text
coverage actual mapped chunk
hierarchical whole-paper reduce
CapabilityContract runtime
```

目标：

```text
长论文从 explicit partial
升级成 whole-paper bounded hierarchy
```

---

## PR-8 — Types / Production Broker

最后做：

```text
OpenAPI contract adoption
remove duplicate RunEvent types
reduce any
RedisBroker / Postgres Broker
broker backpressure metrics
```

---

# 56. 不建议现在做什么

当前阶段不建议再新增：

```text
新的 Agent abstraction
新的 planner 层
新的 event protocol
新的 state manager
新的 UI design system
新的 orchestration framework
```

理由：

```text
这些层现在都已经足够
```

当前收益最高的是：

```text
把真实主链跑完整
把边界 race 修掉
把旧语义删掉
把 integration tests 补起来
```

---

# 57. 需要删除或弃用的旧语义

完成上述修复后建议明确删除：

```text
Run.status = cancelled
作为“Stop current task”的结果
```

真正：

```text
Run terminal
```

只用：

```text
archived / deleted
```

---

删除/弃用 Queue 中：

```python
enqueue_coro(...)
```

兼容 shim。

现在既然 Queue 已经明确：

```text
DB task = source of truth
```

长期不应继续保留“传 coroutine”这个 API 概念。

---

旧测试：

```text
cancelled Run never resumes
```

应删除/改写。

---

Generation：

旧：

```text
single-call nextjs_generator
```

如果没有其它明确兼容用途，V3 稳定后应从 production 路径彻底删除，避免未来又出现两套 generator。

---

Verification：

```text
ready_for_preview
```

仅作为 derived backward-compatible field。

业务代码只使用：

```text
technical_ready
preview_allowed
product_ready
```

---

# 58. 最终 Runtime State Model

建议最终收敛成：

```text
Run / Thread
│
├─ active
├─ running
├─ waiting_user
├─ error
└─ archived_at
   ↓
   真正 thread-level terminal

Task
│
├─ queued
├─ running
├─ waiting_user
├─ waiting_approval
├─ completed
├─ failed
└─ cancelled
```

严格禁止：

```text
Task cancel
→ Run cancelled forever
```

---

# 59. 最终 Agent 执行主链

```text
User Message
↓
Create Task
↓
Queue
↓
Exact claim + lease
↓
Orchestrator
↓
Resource Gate
↓
Tools
│
├─ parse
├─ plan
├─ Generation V3
├─ verify
├─ repair
├─ sandbox
└─ browser acceptance
↓
Runtime readiness recompute
↓
Task completed
↓
Run active
↓
等待下一轮 follow-up
```

连续编辑：

```text
下一条 User Message
↓
新 Task
↓
已有 workspace resource
↓
inspect
↓
read
↓
patch
↓
checks
↓
preview
```

不重新：

```text
parse → generate from zero
```

---

# 60. 最终 Definition of Done

## Main Path

- [x] `generate_nextjs_app_v3()` 真正完整执行通过；
- [x] V3 有 full integration test；
- [x] V3 batch 只允许 planned files；
- [x] V3 使用 SafeWorkspacePolicy；
- [x] atomic promotion 失败可 rollback。

## Continuous Agent

- [x] Stop 只取消当前 Task；
- [x] Interrupt 只取消旧 Task，然后启动新 Task；
- [x] Stop 后 Run 仍可接受后续请求；
- [x] Orchestrator 不再因 `Run.cancelled` 阻止正常 follow-up；
- [x] archive/delete 才是 thread terminal。

## Queue / Scheduler

- [x] replacement callback 不会删除新 task；
- [x] enqueue/worker shutdown 无 race；
- [x] claim loser 不会 requeue winner；
- [x] lease lost 会停止旧 execution；
- [x] Queue 不会把未知 early return 推断为 completed；
- [x] restart recovery 实际执行 queued task；
- [x] 同一 Run 同时最多一个 active Task。

## Verification

- [x] `technical_ready` 正确；
- [x] `preview_allowed` 正确；
- [x] runtime success 写回 gates；
- [x] acceptance success 写回 gates；
- [x] `product_ready` 可从 False 正常变 True；
- [x] nonzero command exit 永远不会 false pass；
- [x] browser upload 不能访问任意本地文件。

## Conversation

- [x] Task chronological order；
- [x] User Message task_id；
- [x] Assistant Message task_id；
- [x] Tool Message task_id；
- [x] Step task_id；
- [x] Artifact task_id；
- [x] Approval task_id；
- [x] SSE 与 reload hydration 后 Turn 完全一致；
- [x] 新数据不应产生 unexplained untracked entities。

## Workbench

- [x] workspace identity change 清理/重验证 editor tabs；
- [x] dirty tab 不可写到另一 workspace；
- [x] iframe 使用 isolated preview URL；
- [x] Open New Tab 也使用同一 `previewSrc`。

## Parser

- [x] Coverage 根据实际成功 map chunk；
- [x] 长论文不只处理开头 16 chunks；
- [x] hierarchical reduction；
- [x] CapabilityContract 真正进入 Planner。

## Production

- [x] in-process broker 单机可靠；
- [x] queue drop 有 metrics；
- [ ] 多 worker 时使用 shared Broker；（按 §49 明确"现在就过度设计，等真正多 worker 时实现"，本次收口不构建）
- [x] lease loss / reclaim 有系统测试。

---

# 61. 当前完成度重新估计

> 以下是工程完整度估计，不是测试覆盖率。

```text
Streaming / Realtime      92%
Workspace Runtime         90%
Task / Turn Domain        84%
Continuous Agent          78%
Generation V3             72%
Verification              82%
Workbench                 90%
Parser / Capability       62%
Durable Scheduler         74%
Multi-worker Production   58%
```

为什么 Generation V3 只有约 72%：

```text
架构已经完成
主链已经接入

但真实 full execution 有直接接口 Bug
且 batch policy 还不严格
```

为什么 Continuous Agent 只有约 78%：

```text
Queue / follow-up 已经有
Run = persistent thread 的大部分逻辑也已转过来

但 Stop / Interrupt 仍使用旧 Run cancellation semantics
```

所以这两个领域当前应优先修。

---

# 62. 文件级施工清单

## `paperforge/agents/generation_v3.py`

立即：

```text
root=temp_dir
→ workspace=temp_dir
```

继续：

```text
+ GeneratedFile
+ GeneratedBatch
+ validate_batch_contract
+ SafeWorkspacePolicy
+ promotion rollback
```

---

## `paperforge/orchestrator/loop.py`

修改：

```text
CancelledError:
Task → cancelled
Run → active
```

删除/调整：

```text
prev_status == cancelled
→ return
```

Thread terminal 只看：

```text
archived_at
```

---

## `api/routes/messages.py`

Interrupt 当前流程保留：

```text
cancel current
→ create new Task
```

但 cancellation 必须 task-level。

建议 API 调用：

```text
cancel active task
```

而不是：

```text
cancel run
```

---

## `api/routes/runs.py`

当前：

```text
POST /runs/{id}/cancel
```

建议：

```text
deprecated
```

新增 Task cancel endpoint。

如果暂时保留旧 endpoint，也要改成：

```text
cancel current active Task
Run → active
```

不要永久 Run.cancelled。

---

## `paperforge/orchestrator/tasks.py`

修：

```text
RunTaskManager done callback identity
worker empty race
claim failure handling
implicit completion
lease-lost cancellation
```

长期删除：

```text
enqueue_coro compatibility shim
```

---

## `paperforge/orchestrator/tools.py`

修改：

```text
_finalize_verification_runtime()
→ update gates
→ recompute_readiness()
```

已有 V3 handler wiring 保留。

---

## `paperforge/agents/verifier.py`

修改：

```text
+ recompute_readiness()
+ _run_checks_streaming aggregates exit code
```

保留：

```text
targeted repair
hard gate model
```

---

## `paperforge/agents/browser_smoke.py`

修改：

```text
upload arbitrary path
→ controlled fixture
```

---

## `paperforge/orchestrator/workspace.py`

修改：

```text
verify_app requires workspace
```

检查其它 ToolSpec 与 handler 真实依赖。

---

## `api/routes/runs.py` hydration serializer

修改：

```python
_to_approval()
+ task_id
+ tool_name
```

---

## `web/lib/run-events.ts`

修改：

```text
approval.requested:
task_id: taskId
```

可选：

```text
unknown → ignored
```

---

## `paperforge/storage/db.py`

Conversation state 使用：

```text
tasks chronological ASC
```

如果管理 API 需要 DESC，拆独立方法：

```text
list_tasks_timeline()
list_tasks_recent()
```

不要让一个排序同时服务两种产品语义。

---

## `web/components/PreviewPanel.tsx`

修改：

```text
appArtifactId change
→ clear/revalidate editor tabs
```

Tab 增加：

```text
workspaceId
```

更安全。

---

## `web/components/workbench/PreviewFrame.tsx`

修改：

```typescript
window.open(
  previewSrc,
  "_blank",
  "noopener,noreferrer",
)
```

---

## `paperforge/agents/paper_parser.py`

立即小修：

```text
processed_chunks
→ actual mapped indices
```

下一阶段：

```text
whole-paper hierarchy
CapabilityContract
```

---

# 63. 审查重点来源

本轮重新读取了当前 `main` 中以下主链文件：

```text
paperforge/agents/generation_v3.py
paperforge/agents/verifier.py
paperforge/agents/browser_smoke.py
paperforge/agents/paper_parser.py

paperforge/orchestrator/loop.py
paperforge/orchestrator/tasks.py
paperforge/orchestrator/tools.py
paperforge/orchestrator/workspace.py
paperforge/orchestrator/events.py

paperforge/storage/db.py

api/routes/messages.py
api/routes/runs.py
api/routes/tasks.py
api/main.py

web/lib/run-events.ts
web/lib/project-turns.ts
web/lib/api.ts
web/lib/store.ts
web/lib/contracts.ts

web/components/Composer.tsx
web/components/ChatPanel.tsx
web/components/PreviewPanel.tsx
web/components/workbench/PreviewFrame.tsx

tests/unit/test_generation_v3.py
tests/unit/test_generation_v3_wiring.py
tests/unit/test_queue_interrupt.py
tests/unit/test_worker_lease.py
tests/test_task_cancel.py
tests/test_run_state_contract.py
tests/e2e/test_full_pipeline.py
tests/e2e/test_user_flows.py
```

---

# 64. 最后建议

现在 PaperForge 的下一轮开发应该只围绕一句话：

> **不要再证明“某个模块存在”，而要证明“用户真正走完整主链时，这些模块能一起正确工作”。**

现在最重要的三件事：

```text
1. 修 Generation V3 当前真实 TypeError
2. 把 Stop / Interrupt 完全改成 Task-level semantics
3. 让 runtime/acceptance 真正把 product_ready 闭环到 True
```

然后马上做：

```text
Queue concurrency hardening
Generation contract hardening
Turn hydration closure
```

只有这些完成以后，再继续 Parser V2、OpenAPI types 和 multi-worker productionization。

如果严格按照本文件的 PR-1 → PR-8 执行，这一轮完成后，PaperForge 才真正可以从：

```text
“很多高级组件已经写出来”
```

进入：

```text
“一个能够连续执行、可恢复、可修改、可验证，
且主链契约一致的论文产品化 Agent Workspace”
```
