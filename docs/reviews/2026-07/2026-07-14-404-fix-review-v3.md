# PaperForge 当前代码复查、404 修复与未完成项清单（V3）

> 审查对象：`Vincent-Wenhan/PaperForge` 当前 `main` 分支  
> 审查日期：2026-07-14  
> 重点：截图中的 Run 工作区 404、当前前后端契约、实时状态、Agent 闭环、沙箱预览、代码编辑与 UI 完成度  
> 说明：本报告以当前仓库代码为准。上一版文档中已经被仓库修复的问题，本版会明确标记，不再当作待修复项。

---

## 0. 结论

当前截图中的错误可以确定为一个前后端 API 契约缺失问题：

```text
RunWorkspacePage
  └── Promise.all(
        GET /api/runs/{id},
        GET /api/artifacts?run_id={id}&include_data=true,
        GET /api/approvals?run_id={id}   ← 后端没有这个 GET 路由
      )
       └── FastAPI 返回 404 {"detail":"Not Found"}
            └── Promise.all 整体失败
                 └── 页面进入全屏 error 分支
                      └── 中央工作区只显示 404
```

对应文件：

```text
web/app/runs/[id]/page.tsx
web/lib/api.ts
api/routes/approvals.py
```

因此，**截图中的 404 不是 Run 不存在，也不是 Next.js 页面路径错误，而是审批列表接口没有实现**。

与此同时，当前代码虽然已经补上了若干之前缺失的能力，例如：

- ProductPlanner 已经真正注入 capability card 内容；
- Generator 已加入业务文件白名单、路径防穿越和依赖白名单；
- BuildRunner 已改为 UUID 容器名并使用 `asyncio.to_thread`；
- Verifier 已经执行 TypeScript、lint 和 build；
- SSE 后端已经持久化事件并实现数据库回放；
- Composer 已加入附件上传、发送锁和失败回滚；

但仍然存在以下结构性问题：

1. Run 页面仍有致命 404；
2. `/state` 返回的数据结构与前端类型不一致；
3. 页面和 ChatPanel 重复水合，SSE 没有使用 cursor；
4. `currentRun` 状态变化会让 SSE effect 反复断开、重连和重新水合；
5. 审批只在内存中等待，服务重启后无法恢复；
6. Agent 仍是不可逆单向阶段机，预览完成后无法继续修改；
7. Verifier 虽然写了 repair loop，但 Orchestrator 没有调用它；
8. `stop_sandbox` 被定义了，却在所有阶段都不允许调用；
9. App 文件 API 和 Sandbox 文件 API 重复且行为不一致；
10. Sandbox 文件 API 无法创建普通目录；
11. Preview proxy 不支持 WebSocket/HMR；
12. PDF 仍直接截断到前 80,000 字符；
13. Library、Settings 的前后端返回结构不一致；
14. UI 目前仍是“功能原型”，并非 ChatGPT/Codex/Claude 级工作台；
15. 缺少真正的浏览器 E2E 测试，所以这类 404 没被发现。

---

# 1. 截图中 404 的精确根因

## 1.1 前端运行页发起了不存在的接口

当前 `web/app/runs/[id]/page.tsx`：

```tsx
useEffect(() => {
  if (!params.id) return;

  setLoading(true);
  setError(null);

  Promise.all([
    api.getRun(params.id),
    api.listArtifacts(params.id, true),
    api.listApprovals(params.id),
  ])
    .then(([run, arts, approvals]) => {
      setCurrentRun(run as Run);
      setArtifacts(arts);

      const pending = approvals.filter(
        (a) => a.status === "pending"
      );
      setPendingApprovals(pending);
      setLoading(false);
    })
    .catch((err) => {
      setError(err.message || "Failed to load run");
      setLoading(false);
    });
}, [params.id]);
```

`web/lib/api.ts`：

```ts
listApprovals: async (runId?: string): Promise<Approval[]> => {
  const q = runId ? `?run_id=${runId}` : "";
  return getJson(`/api/approvals${q}`);
},
```

但当前 `api/routes/approvals.py` 只有：

```python
@router.post("/{approval_id}/resolve")
async def resolve_approval(...):
    ...
```

没有：

```python
@router.get("")
```

因此：

```http
GET /api/approvals?run_id=run_xxx
```

一定返回：

```json
{
  "detail": "Not Found"
}
```

这与截图完全一致。

---

## 1.2 为什么一个审批接口会让整个 Run 页面打不开

因为使用了 `Promise.all`。

`Promise.all` 是 fail-fast：

```text
getRun 成功
listArtifacts 成功
listApprovals 失败
        ↓
整个 Promise.all 失败
        ↓
setError("404: ...")
        ↓
页面只渲染 error 分支
```

审批本来只是可选辅助数据，却被设计成了页面能否打开的硬依赖。

这说明当前页面的数据加载边界不合理。

---

# 2. P0：立刻修复当前 404

## 2.1 后端补齐审批列表接口

建议不要直接把数据库行原样返回，因为数据库字段名与前端字段名不同。

数据库当前返回：

```json
{
  "id": "apv_xxx",
  "run_id": "run_xxx",
  "tool_name": "generate_nextjs_app",
  "args": {},
  "status": "pending"
}
```

前端 `Approval` 类型期待：

```ts
export interface Approval {
  approval_id: string;
  tool: string;
  args: Record<string, unknown>;
  status: "pending" | "approved" | "rejected";
}
```

应在 API 边界统一转换。

### 完整替换：`api/routes/approvals.py`

```python
"""Approvals API routes for HITL flow."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from paperforge.orchestrator.approvals import get_approval_registry
from paperforge.storage.db import get_storage


router = APIRouter()


ApprovalStatus = Literal["pending", "approved", "rejected", "expired"]


class ApprovalResolve(BaseModel):
    approved: bool


class ApprovalView(BaseModel):
    approval_id: str
    run_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: ApprovalStatus
    created_at: str | None = None
    resolved_at: str | None = None


def to_approval_view(row: dict[str, Any]) -> ApprovalView:
    """Normalize storage naming to the public API contract."""

    return ApprovalView(
        approval_id=row["id"],
        run_id=row["run_id"],
        tool=row["tool_name"],
        args=row.get("args") or {},
        status=row["status"],
        created_at=row.get("created_at"),
        resolved_at=row.get("resolved_at"),
    )


@router.get("", response_model=list[ApprovalView])
async def list_approvals(
    run_id: str | None = Query(default=None),
    status: ApprovalStatus | None = Query(default=None),
) -> list[ApprovalView]:
    storage = get_storage()

    if run_id is not None and storage.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")

    rows = storage.list_approvals(run_id=run_id, status=status)
    return [to_approval_view(row) for row in rows]


@router.post("/{approval_id}/resolve", response_model=ApprovalView)
async def resolve_approval(
    approval_id: str,
    req: ApprovalResolve,
) -> ApprovalView:
    storage = get_storage()

    approval = storage.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval already {approval['status']}",
        )

    storage.resolve_approval(approval_id, req.approved)

    registry = get_approval_registry()
    registry.resolve(approval_id, req.approved)

    updated = storage.get_approval(approval_id)
    if not updated:
        raise HTTPException(
            status_code=500,
            detail="Approval disappeared after update",
        )

    return to_approval_view(updated)
```

---

## 2.2 临时前端止血方案

即使后端接口暂时没部署，也不应让审批请求拖垮整个页面。

```tsx
const [runResult, artifactsResult, approvalsResult] =
  await Promise.allSettled([
    api.getRun(params.id),
    api.listArtifacts(params.id, true),
    api.listApprovals(params.id),
  ]);

if (runResult.status === "rejected") {
  throw runResult.reason;
}

setCurrentRun(runResult.value);

if (artifactsResult.status === "fulfilled") {
  setArtifacts(artifactsResult.value);
} else {
  setArtifacts([]);
}

if (approvalsResult.status === "fulfilled") {
  setPendingApprovals(
    approvalsResult.value.filter(
      (approval) => approval.status === "pending"
    )
  );
} else {
  setPendingApprovals([]);
}
```

不过这只是止血，不是最终方案。

最终应删除这一套三请求加载，统一使用已经存在的：

```http
GET /api/runs/{run_id}/state
```

---

# 3. P0：Run 页面应只水合一次

## 3.1 当前重复水合

当前代码存在两套初始化。

Run 页面：

```tsx
api.getRun(...)
api.listArtifacts(...)
api.listApprovals(...)
api.listSandboxes(...)
api.getLatestSandboxForRun(...)
```

ChatPanel：

```tsx
api.getRunState(currentRun.id)
```

同一个页面至少发出：

```text
GET /api/runs
GET /api/library
GET /api/runs/{id}
GET /api/artifacts
GET /api/approvals
GET /api/sandboxes
GET /api/sandboxes/latest
GET /api/runs/{id}/state
GET /api/runs/{id}/events
```

其中 Run、Artifact、Approval、Sandbox 被重复获取。

这种结构会产生：

- 网络请求浪费；
- 较晚返回的旧响应覆盖较新的 SSE 状态；
- 切换 Run 时旧请求污染新 Run；
- 多个地方同时清空、写入 Zustand；
- 很难判断 loading 和 error 属于哪一层。

---

## 3.2 推荐：单一 `useRunSession`

新增：

```text
web/hooks/useRunSession.ts
```

```tsx
"use client";

import { useEffect, useState } from "react";

import { api, SSEClient, toApiError } from "@/lib/api";
import { normalizeRunState } from "@/lib/contracts";
import { registerRunEventHandlers } from "@/lib/run-events";
import { useAppStore } from "@/lib/store";

export function useRunSession(runId?: string) {
  const [loading, setLoading] = useState(Boolean(runId));
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!runId) return;

    let disposed = false;
    let sse: SSEClient | null = null;

    async function start() {
      setLoading(true);
      setError(null);

      try {
        const rawState = await api.getRunState(runId);
        if (disposed) return;

        const state = normalizeRunState(rawState);
        useAppStore.getState().hydrateRunSession(state);

        sse = new SSEClient();
        registerRunEventHandlers(sse, runId);

        // 必须从水合快照的 cursor 之后接收。
        sse.connect(runId, state.event_cursor);
      } catch (cause) {
        if (!disposed) {
          setError(toApiError(cause).userMessage);
        }
      } finally {
        if (!disposed) {
          setLoading(false);
        }
      }
    }

    void start();

    return () => {
      disposed = true;
      sse?.disconnect();
    };
  }, [runId, reloadKey]);

  return {
    loading,
    error,
    retry: () => setReloadKey((value) => value + 1),
  };
}
```

Run 页面只保留：

```tsx
export default function RunWorkspacePage() {
  const params = useParams<{ id: string }>();
  const { loading, error, retry } = useRunSession(params.id);

  // runs 和 library 可以由独立 SidebarQuery 获取，
  // 不参与主 workspace 是否可用的判断。
}
```

ChatPanel 不再负责加载状态，只负责展示：

```tsx
export function ChatPanel() {
  const messages = useAppStore((s) => s.messages);
  const events = useAppStore((s) => s.events);

  return (
    // render only
  );
}
```

---

# 4. P0：`/state` 当前也没有真正满足它自己的设计目标

当前注释说 `/state` 会返回：

```text
run
messages
artifacts
sandbox
pending_approvals
event_cursor
```

但实现仍有四个问题。

---

## 4.1 Approval 字段结构错误

当前直接：

```python
approvals = storage.list_approvals(
    run_id=run_id,
    status="pending",
)
```

返回的是：

```text
id
tool_name
```

前端期待：

```text
approval_id
tool
```

因此刷新页面后审批卡可能出现：

```text
approval_id = undefined
tool = undefined
```

应复用统一 DTO 转换。

---

## 4.2 Artifact 不包含 `data`

当前：

```python
artifacts = storage.list_artifacts(run_id=run_id)
```

`list_artifacts()` 只读取 SQLite 行，不读取 JSON 文件内容。

所以刷新后：

```tsx
verification?.data
```

为空。

结果是：

- Tests tab 无法恢复验证报告；
- Artifact 详情数据缺失；
- PRD、Capability Card 只显示元信息；
- 页面刚生成时可以看，刷新后不能看。

应做轻量摘要与按需详情两种模式，或者在 state 中只对小型 artifact hydrate data。

---

## 4.3 Sandbox 不是最新一个

当前：

```python
sandboxes = storage.list_sandboxes()
run_sandboxes = [s for s in sandboxes if s.get("run_id") == run_id]
sandbox = run_sandboxes[0] if run_sandboxes else None
```

而 `list_sandboxes()` 没有 `ORDER BY`。

`run_sandboxes[0]` 不保证是最新的，也不保证是 running 的。

仓库已经有：

```python
storage.get_latest_sandbox_for_run(run_id)
```

应该直接使用。

---

## 4.4 event cursor 只看内存，不看数据库

当前：

```python
history = event_manager.get_history(run_id)
event_cursor = max((e.seq for e in history), default=0)
```

但 SSE 事件已经持久化到 SQLite。

后端重启后：

```text
数据库中 seq = 128
内存 history = []
/state event_cursor = 0
```

前端会从 0 重播全部历史事件。

正确实现应是：

```python
event_cursor = storage.get_max_event_seq(run_id)
```

---

## 4.5 完整替换：`get_run_state`

```python
from api.routes.approvals import to_approval_view


def hydrate_artifact_summary(storage, row: dict) -> dict:
    """Hydrate data only for small structured artifacts."""

    artifact_type = row.get("type")

    if artifact_type not in {
        "capability_card",
        "composition",
        "prd",
        "verification_report",
    }:
        return row

    full = storage.get_artifact(row["id"])
    return full or row


@router.get("/{run_id}/state")
async def get_run_state(run_id: str) -> dict:
    storage = get_storage()

    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    messages = storage.list_messages(run_id)

    artifact_rows = storage.list_artifacts(run_id=run_id)
    artifacts = [
        hydrate_artifact_summary(storage, row)
        for row in artifact_rows
    ]

    sandbox = storage.get_latest_sandbox_for_run(run_id)

    approval_rows = storage.list_approvals(
        run_id=run_id,
        status="pending",
    )
    approvals = [
        to_approval_view(row).model_dump()
        for row in approval_rows
    ]

    event_cursor = storage.get_max_event_seq(run_id)

    return {
        "run": _to_run(run).model_dump(),
        "messages": messages,
        "artifacts": artifacts,
        "sandbox": sandbox,
        "pending_approvals": approvals,
        "event_cursor": event_cursor,
    }
```

---

# 5. P0：前端 SSE 仍没有使用后端已经实现的断线续传

后端现在已经支持：

```http
GET /api/runs/{run_id}/events?after_seq=123
```

也支持：

```http
Last-Event-ID: 123
```

但当前前端仍然：

```ts
connect(runId: string) {
  this.es = new EventSource(
    buildUrl(`/api/runs/${runId}/events`)
  );
}
```

没有使用 `/state` 返回的 `event_cursor`。

---

## 5.1 修改 SSE Client

```ts
export class SSEClient {
  private es: EventSource | null = null;
  private handlers = new Map<
    string,
    Set<(payload: unknown) => void>
  >();

  private seenSeqs = new Set<number>();

  connect(runId: string, afterSeq: number = 0): void {
    this.disconnect();
    this.seenSeqs.clear();

    const params = new URLSearchParams({
      after_seq: String(afterSeq),
    });

    const url = buildUrl(
      `/api/runs/${runId}/events?${params}`
    );

    const source = new EventSource(url);
    this.es = source;

    const eventTypes = [
      "message.started",
      "message.delta",
      "message.completed",
      "message.failed",
      "run.started",
      "run.finished",
      "run.error",
      "run.status.changed",
      "task.phase.changed",
      "tool.call",
      "tool.result",
      "artifact.created",
      "approval.requested",
      "approval.resolved",
      "sandbox.started",
      "sandbox.error",
      "preview.ready",
      "stream.gap",
    ];

    for (const type of eventTypes) {
      source.addEventListener(
        type,
        (rawEvent: MessageEvent<string>) => {
          const envelope = JSON.parse(rawEvent.data) as {
            id: string;
            seq: number;
            run_id: string;
            type: string;
            payload: unknown;
          };

          if (this.seenSeqs.has(envelope.seq)) return;
          this.seenSeqs.add(envelope.seq);
          this.emit(envelope.type, envelope.payload);
        }
      );
    }

    source.onerror = () => {
      // EventSource 自己负责重连。
      // 页面只更新 connection 状态，不要立即重新 hydrate。
    };
  }

  disconnect(): void {
    this.es?.close();
    this.es = null;
  }

  on(
    type: string,
    handler: (payload: any) => void,
  ): () => void {
    const set = this.handlers.get(type) ?? new Set();
    set.add(handler);
    this.handlers.set(type, set);

    return () => {
      set.delete(handler);
    };
  }

  private emit(type: string, payload: unknown): void {
    for (const handler of this.handlers.get(type) ?? []) {
      handler(payload);
    }
  }
}
```

---

# 6. P0：`ChatPanel` 的 effect 会反复重连 SSE

当前依赖：

```tsx
useEffect(() => {
  ...
}, [
  currentRun,
  ...
]);
```

但 SSE 事件中又执行：

```tsx
updateCurrentRun({
  status: data.status,
});
```

以及：

```tsx
updateCurrentRun({
  phase: data.phase,
});
```

`updateCurrentRun` 会创建新的对象：

```ts
currentRun: {
  ...s.currentRun,
  ...patch,
}
```

于是：

```text
收到 run.status.changed
  ↓
currentRun 对象引用变化
  ↓
ChatPanel effect cleanup
  ↓
SSE disconnect
  ↓
重新请求 /state
  ↓
重新 connect
  ↓
收到 task.phase.changed
  ↓
再次循环
```

这会造成：

- 频繁断开重连；
- delta 丢失或重复；
- 页面闪烁；
- 旧 state 覆盖实时消息；
- 对话越长越不稳定。

正确依赖应该只使用：

```tsx
const runId = currentRun?.id;

useEffect(() => {
  if (!runId) return;
  ...
}, [runId]);
```

更好的做法仍然是把 SSE 从 ChatPanel 移到 `useRunSession`。

---

# 7. P0：审批恢复仍未完成

当前审批流程：

```text
创建 SQLite approval row
  ↓
在 ApprovalRegistry 中创建 asyncio.Event
  ↓
Orchestrator await event.wait()
  ↓
API resolve 时设置内存 Event
```

问题是 `ApprovalRegistry` 完全在内存中。

后端重启后：

```text
SQLite 中 approval 仍是 pending
内存中的 asyncio.Event 已丢失
原 orchestrator task 已丢失
```

此时用户即使点击 Approve：

```python
registry.resolve(approval_id, approved)
```

也会返回 `False`，因为 registry 中没有该 ID。

所以当前只是“审批记录持久化”，不是“审批任务可恢复”。

---

## 7.1 最小改法：轮询数据库状态

不使用内存 Event 作为唯一真相。

```python
async def wait_for_approval(
    approval_id: str,
    storage: Storage,
    timeout_s: int,
) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_s

    while True:
        row = await asyncio.to_thread(
            storage.get_approval,
            approval_id,
        )

        if row is None:
            raise RuntimeError(
                f"Approval disappeared: {approval_id}"
            )

        status = row["status"]

        if status == "approved":
            return True

        if status == "rejected":
            return False

        if asyncio.get_running_loop().time() >= deadline:
            storage.expire_approval(approval_id)
            raise TimeoutError(
                f"Approval timed out: {approval_id}"
            )

        await asyncio.sleep(0.5)
```

但这仍不能恢复已经丢失的 orchestrator task。

长期应采用：

```text
task checkpoint
+ resumable job
+ approval blocking state
```

---

# 8. P0：Run cancel 后数据库状态可能仍停在 running

当前 `cancel_run` 只取消内存任务：

```python
cancelled = task_manager.cancel(run_id)
return {
    "status": "cancelled",
}
```

没有：

```python
storage.update_run_status(
    run_id,
    "cancelled",
)
```

而 `asyncio.CancelledError` 不应依靠普通的：

```python
except Exception:
```

处理。

因此可能出现：

```text
任务已停止
数据库状态仍为 running
Composer 一直显示 Stop
Sidebar 一直显示 running
```

建议：

```python
@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict:
    storage = get_storage()

    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    task_manager = get_run_task_manager()
    cancelled = task_manager.cancel(run_id)

    if not cancelled:
        raise HTTPException(
            status_code=409,
            detail="Run is not active",
        )

    previous_status = run.get("status")
    storage.update_run_status(run_id, "cancelled")

    emitter = EventEmitter(run_id, get_event_manager())
    await emitter.run_status_changed(
        "cancelled",
        previous_status,
    )

    return {
        "status": "cancelled",
        "run_id": run_id,
    }
```

Orchestrator 还应单独处理：

```python
except asyncio.CancelledError:
    self.storage.update_run_status(run_id, "cancelled")
    await emit.run_status_changed("cancelled", "running")
    raise
```

---

# 9. P0：Agent 工作流仍然是不可逆单向状态机

当前阶段：

```python
INIT
PARSED
COMPOSED
PLANNED
GENERATED
VERIFIED
PREVIEW_READY
DONE
ERROR
```

阶段允许工具：

```python
PREVIEW_READY: {"finish"}
DONE: set()
ERROR: set()
```

所以用户在预览后说：

```text
把页面改成深色
修一下按钮
重新生成 PRD
修复 build
重启 preview
```

Agent 都无法正常执行对应工具。

当前 UI 中虽然有：

```text
Revise PRD
Fix build
Restart preview
```

但这些按钮只是把一句自然语言填进输入框：

```tsx
setInput(
  "Fix the failing build based on..."
)
```

它们不是命令，也没有绕过 phase gate。

---

## 9.1 当前 `stop_sandbox` 实际不可调用

工具定义里有：

```python
ToolDefinition(
    name="stop_sandbox",
    ...
)
```

dispatcher 里也有：

```python
"stop_sandbox": handle_stop_sandbox
```

但 `ALLOWED_TOOLS` 的任何阶段都没有它。

所以 LLM 无论在哪个阶段调用：

```text
stop_sandbox
```

都会被 phase gate 拒绝。

这是典型的“代码写了，但链路没接通”。

---

## 9.2 `build_and_repair()` 写了但没有接入

`verifier.py` 已经有：

```python
async def build_and_repair(...):
    ...
```

但 `handle_verify()` 实际调用的是：

```python
from paperforge.agents.verifier import verify_app

report = await verify_app(...)
```

没有调用：

```python
build_and_repair(...)
```

所以当前 UI 的“Fix build”并不会自动触发现有 repair loop。

---

## 9.3 `finish` 后状态语义也不一致

`handle_finish()` 返回：

```python
next_phase="done",
stop_loop=True,
```

但 Orchestrator 在 stop_loop 时又执行：

```python
self.storage.update_run_status(
    run_id,
    "active",
)
```

于是可能形成：

```text
phase = done
status = active
```

这两个状态表达相互冲突。

---

## 9.4 推荐：状态机改为 Artifact 前置条件

不要用“走过后不能回头”的阶段门禁。

```python
ACTION_REQUIREMENTS = {
    "parse_paper": set(),
    "compose_capabilities": {"capability_card"},
    "plan_product": {"capability_card"},
    "generate_nextjs_app": {"prd"},
    "verify_app": {"nextjs_app"},
    "repair_app": {
        "nextjs_app",
        "verification_report",
    },
    "run_in_sandbox": {"nextjs_app"},
    "restart_sandbox": {"sandbox"},
    "stop_sandbox": {"sandbox"},
}
```

判断：

```python
def can_execute(
    tool_name: str,
    context: WorkflowContext,
) -> tuple[bool, str | None]:
    required = ACTION_REQUIREMENTS.get(tool_name, set())

    missing = [
        item
        for item in required
        if not context.has(item)
    ]

    if missing:
        return (
            False,
            "Missing prerequisites: " + ", ".join(missing),
        )

    return True, None
```

这样支持：

```text
plan
  → generate
  → verify
  → repair
  → verify
  → preview
  → user feedback
  → repair or regenerate
  → verify
  → restart preview
```

---

# 10. P1：把现有 Repair Loop 真正接入

新增工具：

```python
ToolDefinition(
    name="repair_app",
    description=(
        "Repair a generated app using the latest "
        "verification report, then re-run verification."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "app_path": {"type": "string"},
            "prd_id": {"type": "string"},
            "max_attempts": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3,
            },
        },
        "required": ["app_path"],
    },
)
```

handler：

```python
async def handle_repair(
    args: dict[str, Any],
    ctx: ToolContext,
) -> ToolResult:
    from paperforge.agents.verifier import build_and_repair

    report = await build_and_repair(
        app_path=args["app_path"],
        prd_id=args.get("prd_id"),
        llm=ctx.llm,
        storage=ctx.storage,
        max_attempts=min(int(args.get("max_attempts", 3)), 3),
    )

    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="verification_report",
        data=report,
    )

    await ctx.emit.artifact_created(
        "verification_report",
        str(ctx.storage.reports_dir),
        artifact_id,
    )

    ready = bool(report.get("ready_for_preview"))

    return ToolResult(
        tool="repair_app",
        status=(
            ToolStatus.SUCCEEDED
            if ready
            else ToolStatus.FAILED
        ),
        artifact_id=artifact_id,
        data={"report": report},
        summary=(
            "Repair completed."
            if ready
            else "Repair attempts exhausted."
        ),
        retryable=not ready,
    )
```

---

# 11. P1：Sandbox 管理仍然没有统一

应用 lifespan 中已经创建：

```python
app.state.sandbox_manager
```

但 route 和 tool handler 又反复：

```python
manager = DockerSandboxManager(storage=storage)
```

这会导致：

- monitor 使用一个 manager；
- route 使用另一个 manager；
- agent tool 又使用另一个 manager；
- 资源限制和内部状态无法统一；
- shutdown_all 只能处理 lifespan manager 认识的实例状态；
- 日志、端口、容器缓存可能分裂。

应使用 FastAPI dependency：

```python
from fastapi import Request


def get_sandbox_manager(
    request: Request,
) -> DockerSandboxManager:
    manager = getattr(
        request.app.state,
        "sandbox_manager",
        None,
    )

    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="Docker sandbox is unavailable",
        )

    return manager
```

route：

```python
@router.post("")
async def start_sandbox(
    req: SandboxStart,
    manager: DockerSandboxManager = Depends(get_sandbox_manager),
) -> dict:
    return await manager.start(
        run_id=req.run_id or "",
        app_path=req.app_path,
    )
```

Agent 侧不要直接 new manager，应通过统一 service 层：

```text
SandboxService
  ├── start
  ├── stop
  ├── restart
  ├── logs
  ├── health
  └── resolve_app
```

---

# 12. P1：不应让前端提交任意 `app_path`

当前 API：

```ts
startSandbox(
  runId: string,
  appPath: string
)
```

后端请求：

```python
class SandboxStart(BaseModel):
    app_path: str
    run_id: str | None = None
```

这意味着客户端控制服务器文件系统路径。

更合理的是：

```ts
startSandbox(
  runId: string,
  appArtifactId: string
)
```

后端自行从 artifact metadata 解析：

```python
class SandboxStart(BaseModel):
    run_id: str
    app_artifact_id: str


def resolve_app_path(
    storage: Storage,
    artifact_id: str,
) -> Path:
    artifact = storage.get_artifact(artifact_id)

    if not artifact:
        raise HTTPException(
            status_code=404,
            detail="App artifact not found",
        )

    if artifact["type"] != "nextjs_app":
        raise HTTPException(
            status_code=400,
            detail="Artifact is not an app",
        )

    app_path = artifact.get("metadata", {}).get("app_path")

    if not app_path:
        raise HTTPException(
            status_code=500,
            detail="App path metadata missing",
        )

    return Path(app_path)
```

---

# 13. P1：Preview proxy 不支持 Next.js HMR

当前 preview 使用普通 `httpx` HTTP proxy：

```python
target_url = f"http://localhost:{port}/{path}"
```

它没有代理 WebSocket。

Next.js dev server 的热更新依赖 WebSocket/HMR 通道，因此可能出现：

- 编辑代码后 iframe 不刷新；
- `_next/webpack-hmr` 连接失败；
- 页面只能手动刷新；
- 某些 redirect、cookie path、绝对路径错误；
- path-prefix 下资源地址错位。

建议最终改成：

```text
https://{sandbox_id}.preview.paperforge.local/
```

由 Caddy、Traefik 或自建 gateway 根据 hostname 路由。

开发阶段至少需要明确代理：

```text
HTTP
WebSocket upgrade
Location header rewrite
Set-Cookie Path rewrite
Origin / Host rewrite
```

---

# 14. P1：Sandbox 文件 API 的目录操作仍然有明确 bug

当前 `_resolve_safe()` 无论处理文件还是目录，都要求扩展名：

```python
if full_path.suffix.lower() not in ALLOWED_EXTS:
    raise HTTPException(...)
```

所以：

```text
components
lib/hooks
app/dashboard
```

这些目录没有后缀，会被 403 拒绝。

但前端类型明确支持：

```ts
type: "file" | "directory"
```

因此“新建文件夹”入口存在，但 backend contract 不支持。

---

## 14.1 修复安全路径函数

```python
def _resolve_safe(
    sandbox: dict,
    file_path: str,
    *,
    require_file_extension: bool,
) -> Path:
    if not file_path:
        raise HTTPException(
            status_code=400,
            detail="Empty file path",
        )

    base = Path(sandbox["app_path"]).resolve()
    target = (base / file_path).resolve()

    try:
        target.relative_to(base)
    except (ValueError, RuntimeError):
        raise HTTPException(
            status_code=403,
            detail="Path outside sandbox",
        )

    relative_parts = target.relative_to(base).parts

    if any(part in BLOCKED_PARTS for part in relative_parts):
        raise HTTPException(
            status_code=403,
            detail="Blocked path segment",
        )

    if (
        require_file_extension
        and target.suffix.lower() not in ALLOWED_EXTS
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Unsupported file type: "
                f"{target.suffix or '(none)'}"
            ),
        )

    return target
```

创建：

```python
@router.post("/sandboxes/{sandbox_id}/entries")
async def create_entry(
    sandbox_id: str,
    req: FileCreate,
) -> dict:
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)

    if not sandbox:
        raise HTTPException(
            status_code=404,
            detail="Sandbox not found",
        )

    is_file = req.type == "file"
    is_directory = req.type == "directory"

    if not is_file and not is_directory:
        raise HTTPException(
            status_code=422,
            detail="type must be file or directory",
        )

    target = _resolve_safe(
        sandbox,
        req.path,
        require_file_extension=is_file,
    )

    if target.exists():
        raise HTTPException(
            status_code=409,
            detail="Entry already exists",
        )

    if is_directory:
        target.mkdir(parents=True, exist_ok=False)
    else:
        content_bytes = req.content.encode("utf-8")

        if len(content_bytes) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail="Content too large",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content_bytes)

    return {
        "path": req.path,
        "created": True,
    }
```

---

## 14.2 当前写文件检查了旧文件大小，而不是新内容大小

当前：

```python
if (
    full_path.exists()
    and full_path.stat().st_size > MAX_FILE_SIZE
):
    ...
```

对于一个新文件：

```text
原文件不存在
req.content = 100 MB
```

检查直接绕过。

应检查：

```python
payload = req.content.encode("utf-8")

if len(payload) > MAX_FILE_SIZE:
    raise HTTPException(
        status_code=413,
        detail="Content too large",
    )
```

---

# 15. P1：存在两套重复文件 API

当前同时有：

```text
/api/files/sandboxes/{sandbox_id}/...
/api/apps/{app_id}/...
```

但 PreviewPanel 只使用 sandbox API：

```ts
api.getFileTree(sandbox.id)
api.readFile(sandbox.id, path)
api.writeFile(sandbox.id, path, ...)
```

结果：

- 没启动 sandbox 就不能看代码；
- App API 基本没有被 UI 使用；
- 两套安全校验实现不一致；
- 目录 bug 一套有、一套没有；
- 修复要改两遍；
- 后续 revision/diff 更难维护。

建议统一成：

```text
WorkspaceService
  ├── resolve_by_app_artifact
  ├── resolve_by_sandbox
  ├── list_tree
  ├── read
  ├── write
  ├── create
  ├── move
  ├── delete
  ├── snapshot
  └── diff
```

API 主入口使用 app artifact：

```text
/api/apps/{app_artifact_id}/workspace/...
```

sandbox 只负责执行，不作为代码所有权实体。

---

# 16. P1：Library 前后端契约不一致

前端：

```ts
getPaper(
  paperId
): Promise<{
  paper: Paper;
  capability_card: any;
}>
```

后端：

```python
return {
    "paper": paper
}
```

没有 `capability_card`。

所以 Library detail 页面即使论文已经解析，也拿不到能力卡正文。

建议：

```python
@router.get("/{paper_id}")
async def get_paper(paper_id: str) -> dict:
    storage = get_storage()

    paper = storage.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    capability_card = None

    card_path = paper.get("card_path")
    if card_path:
        path = Path(card_path)
        if path.exists():
            capability_card = json.loads(
                path.read_text(encoding="utf-8")
            )

    return {
        "paper": paper,
        "capability_card": capability_card,
    }
```

---

## 16.1 Sidebar 的 PDF 下载没有真正触发浏览器下载

当前：

```ts
await api.downloadPaperPdf(paperId);
```

只是拿到了 Blob，没有：

```text
createObjectURL
anchor.click
revokeObjectURL
```

应封装：

```ts
export async function downloadBlob(
  blob: Blob,
  filename: string,
): Promise<void> {
  const url = URL.createObjectURL(blob);

  try {
    const anchor = document.createElement("a");

    anchor.href = url;
    anchor.download = filename;
    anchor.style.display = "none";

    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
```

使用：

```ts
const blob = await api.downloadPaperPdf(paperId);
downloadBlob(blob, `${paperId}.pdf`);
```

---

## 16.2 上传只检查文件名后缀

当前只判断：

```python
file.filename.lower().endswith(".pdf")
```

没有限制：

- 文件大小；
- MIME；
- PDF magic bytes；
- 空文件；
- 加密/损坏 PDF。

建议：

```python
MAX_PDF_BYTES = 50 * 1024 * 1024


async def validate_pdf(file: UploadFile) -> bytes:
    data = await file.read(MAX_PDF_BYTES + 1)

    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=413,
            detail="PDF exceeds 50 MB",
        )

    if not data.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="Invalid PDF signature",
        )

    if not data.strip():
        raise HTTPException(
            status_code=400,
            detail="Empty file",
        )

    return data
```

---

# 17. P1：Settings 页面前后端几乎没有对齐

后端返回：

```python
llm_provider
llm_model
max_sandboxes
docker_available
```

前端期待：

```ts
orchestrator_model
composer_model
planner_model
parser_model
generator_model
verifier_model
sandbox_base_port
max_iterations
llm_max_retries
```

所以页面多数位置只能显示：

```text
—
```

此外当前 Settings 页面只有 GET，没有保存接口，本质上是只读信息页，不是设置页。

推荐至少统一 DTO：

```python
class SettingsView(BaseModel):
    llm_provider: str

    orchestrator_model: str
    composer_model: str
    planner_model: str
    parser_model: str
    generator_model: str
    verifier_model: str

    docker_available: bool
    sandbox_image: str
    max_sandboxes: int
    sandbox_base_port: int

    max_iterations: int
    llm_max_retries: int
```

如果环境变量是唯一配置来源，页面标题应改成：

```text
Runtime Configuration
```

并明确：

```text
Read only · edit .env and restart server
```

而不是给用户“可以修改”的错觉。

---

# 18. P1：PDF Parser 仍然直接截断前 80,000 字符

当前：

```python
if len(text) > 80000:
    text = text[:80000]
```

这会偏向论文前半部分，可能丢失：

- 实验设置；
- 消融；
- 局限；
- 失败案例；
- 附录算法；
- 数据许可；
- 真实部署要求。

尤其 PaperForge 的目标是产品化，这些信息反而决定产品能不能做。

---

## 18.1 推荐 Page-aware Map-Reduce

```python
from dataclasses import dataclass


@dataclass
class PageChunk:
    chunk_id: str
    page_start: int
    page_end: int
    text: str


def split_pages(
    pages: list[str],
    max_chars: int = 18_000,
) -> list[PageChunk]:
    chunks: list[PageChunk] = []

    buffer: list[str] = []
    start_page = 1
    current_chars = 0

    for index, page_text in enumerate(pages, start=1):
        if (
            buffer
            and current_chars + len(page_text) > max_chars
        ):
            chunks.append(
                PageChunk(
                    chunk_id=f"pages_{start_page}_{index - 1}",
                    page_start=start_page,
                    page_end=index - 1,
                    text="\n\n".join(buffer),
                )
            )

            buffer = []
            start_page = index
            current_chars = 0

        buffer.append(page_text)
        current_chars += len(page_text)

    if buffer:
        chunks.append(
            PageChunk(
                chunk_id=f"pages_{start_page}_{len(pages)}",
                page_start=start_page,
                page_end=len(pages),
                text="\n\n".join(buffer),
            )
        )

    return chunks
```

每块提取：

```json
{
  "problem": [],
  "methods": [],
  "inputs_outputs": [],
  "assets": [],
  "evaluation": [],
  "limitations": [],
  "deployment_constraints": [],
  "evidence": [
    {
      "page": 12,
      "claim": "..."
    }
  ]
}
```

最后 reduce：

```python
async def reduce_capability_evidence(
    chunk_results: list[dict],
    llm: LLMClient,
) -> CapabilityCard:
    ...
```

这样 capability card 才能追溯到页码，而不是一段不可验证的总结。

---

# 19. P1：Run Sidebar 的状态和标题不会实时同步

后端会在第一条消息后自动更新标题：

```python
storage.update_run(
    run_id=run_id,
    title=new_title,
)
```

但 Sidebar 的 `runs` 是 Run 页面自己的 local state：

```tsx
const [runs, setRuns] = useState([]);
```

SSE 只更新 Zustand 中的：

```tsx
currentRun
```

没有更新页面 local `runs`。

所以会出现截图里的大量：

```text
New Run
New Run
New Run
```

即使后端已经自动命名，Sidebar 也可能等刷新后才更新。

推荐将 runs 也归一化到一个 store：

```ts
interface RunsState {
  runIds: string[];
  runsById: Record<string, Run>;

  upsertRun(run: Run): void;
  patchRun(
    runId: string,
    patch: Partial<Run>,
  ): void;
}
```

收到事件时：

```ts
patchRun(runId, {
  status: payload.status,
});

patchRun(runId, {
  phase: payload.phase,
});
```

发送第一条消息成功后：

```ts
const updatedRun = await api.getRun(runId);
upsertRun(updatedRun);
```

更好的是后端发：

```text
run.updated
```

事件，其中包含 title/status/phase/updated_at。

---

# 20. P1：UI 仍然是功能骨架，而不是完整工作台

从截图和代码看，当前 UI 的主要问题不是颜色，而是信息架构与交互层级没有完成。

---

## 20.1 顶栏仍是占位级实现

当前顶栏只有：

```text
Search or run a command...
☾
```

缺少：

- 产品标识；
- 当前 Run 标题；
- 运行状态；
- 模型信息；
- 连接状态；
- Share/Export；
- Settings；
- 工作区模式；
- 当前任务进度。

建议顶栏：

```text
[Logo PaperForge] [Run title ▼]
              [Connected] [Model]
              [Share] [Export] [•••]
```

---

## 20.2 Sidebar 没有当前选中态

`RunRow` 只接收：

```ts
run
onSelect
```

没有：

```ts
selected
```

用户不知道自己打开的是哪个 Run。

应加入：

```tsx
<RunRow
  selected={run.id === currentRunId}
/>
```

样式：

```tsx
className={cn(
  "group relative rounded-lg px-2.5 py-2",
  "transition-colors",
  selected
    ? "bg-neutral-200/70 dark:bg-neutral-800"
    : "hover:bg-neutral-100 dark:hover:bg-neutral-900"
)}
```

选中标识：

```tsx
{selected && (
  <span
    className="
      absolute inset-y-2 left-0
      w-0.5 rounded-r
      bg-foreground
    "
  />
)}
```

---

## 20.3 页面错误态占据整个空白画布

当前 error 分支只显示：

```text
404: {"detail":"Not Found"}
New Run
Back to home
```

这既不告诉用户哪个请求失败，也没有 retry 和诊断信息。

建议：

```tsx
<WorkspaceError
  title="Couldn’t open this run"
  description={error.userMessage}
  endpoint={error.endpoint}
  requestId={error.requestId}
  onRetry={retry}
  onBack={() => router.push("/")}
  onOpenDiagnostics={() => setDiagnosticsOpen(true)}
/>
```

并保持 Sidebar 和 Header 可用，不要整个工作台卸载。

---

## 20.4 Changes 不是 Changes

当前 Changes tab 展示的是：

```text
tool.call
tool.result
JSON args
JSON result
```

这叫 Agent Activity，不是文件变更。

真正的 Changes 应展示：

```text
M app/page.tsx
M lib/mock-api.ts
A components/ResultCard.tsx
```

并支持：

```text
unified diff
side-by-side diff
accept
revert file
restore checkpoint
```

数据模型：

```python
class WorkspaceRevision(BaseModel):
    revision_id: str
    app_id: str
    parent_revision_id: str | None
    source: Literal[
        "generator",
        "repair",
        "user_edit",
    ]
    changed_files: list[str]
    created_at: str
```

---

## 20.5 Tests tab 还不是测试工作台

现在 Tests 只是把 verification artifact 映射成四行：

```text
Build
Type check
Lint
Preview
```

缺少：

- Run tests；
- Rerun failed；
- 查看完整日志；
- 失败定位到文件/行；
- Browser smoke test；
- console error；
- failed request；
- screenshot；
- trace；
- 每轮 repair 的历史。

建议：

```text
Tests
├── Static
│   ├── TypeScript
│   └── ESLint
├── Build
│   └── Next.js production build
├── Runtime
│   ├── Server health
│   ├── Browser load
│   ├── Console errors
│   └── Network failures
└── Product acceptance
    ├── Primary CTA works
    ├── Main workflow completes
    └── Result state renders
```

---

## 20.6 Code editor 强制浅色主题

当前：

```tsx
theme="vs-light"
```

即使整个应用处于 dark mode，编辑器仍然亮白。

应根据 theme：

```tsx
const { theme } = useTheme();

<MonacoEditor
  theme={
    theme === "dark"
      ? "vs-dark"
      : "vs-light"
  }
/>
```

---

## 20.7 多数操作失败只写 console

例如：

```tsx
console.error(
  "Failed to save file:",
  err
);
```

用户界面没有反馈。

必须统一：

```tsx
toast({
  title: "Save failed",
  description: toApiError(err).userMessage,
  variant: "error",
});
```

同时保存状态：

```text
Saving…
Saved
Save failed · Retry
```

---

# 21. 推荐的新工作台结构

```tsx
<AppShell>
  <TopBar />

  <WorkspaceLayout>
    <NavigationSidebar>
      <NewRunButton />
      <RunSearch />
      <RunList />
      <LibraryList />
    </NavigationSidebar>

    <ConversationColumn>
      <RunContextBar />
      <MessageTimeline />
      <AgentProgress />
      <ApprovalLayer />
      <Composer />
    </ConversationColumn>

    <WorkbenchColumn>
      <WorkbenchToolbar />

      <WorkbenchTabs>
        <PreviewTab />
        <CodeTab />
        <ChangesTab />
        <TestsTab />
        <ArtifactsTab />
        <LogsTab />
      </WorkbenchTabs>
    </WorkbenchColumn>
  </WorkspaceLayout>
</AppShell>
```

桌面宽度：

```text
Sidebar:       248–280 px
Conversation:  520–720 px
Workbench:     remaining
```

Workbench 可隐藏：

```text
Chat mode
Split mode
Workbench mode
```

不要始终显示大面积空白。

---

## 21.1 Shell 代码骨架

```tsx
export function RunWorkspace({
  runId,
}: {
  runId: string;
}) {
  const {
    loading,
    error,
  } = useRunSession(runId);

  return (
    <div className="
      h-dvh
      bg-background
      text-foreground
      overflow-hidden
    ">
      <TopBar />

      <div className="
        grid h-[calc(100dvh-48px)]
        grid-cols-[260px_minmax(440px,0.9fr)_minmax(520px,1.35fr)]
      ">
        <NavigationSidebar />

        <main className="
          min-w-0
          border-l border-border/70
        ">
          {loading ? (
            <ConversationSkeleton />
          ) : error ? (
            <InlineWorkspaceError
              error={error}
            />
          ) : (
            <ConversationColumn />
          )}
        </main>

        <aside className="
          min-w-0
          border-l border-border/70
          bg-surface-subtle
        ">
          <Workbench />
        </aside>
      </div>
    </div>
  );
}
```

---

## 21.2 更接近 ChatGPT/Codex 的设计 token

```css
:root {
  --app-bg: 0 0% 98.5%;
  --panel-bg: 0 0% 100%;
  --panel-subtle: 240 5% 97%;
  --panel-raised: 0 0% 100%;

  --text-strong: 240 10% 8%;
  --text-normal: 240 6% 22%;
  --text-muted: 240 4% 46%;

  --line-soft: 240 6% 91%;
  --line-strong: 240 5% 83%;

  --interactive: 240 6% 10%;
  --interactive-hover: 240 6% 18%;

  --radius-sm: 7px;
  --radius-md: 10px;
  --radius-lg: 14px;

  --shadow-float:
    0 8px 30px rgba(0, 0, 0, 0.08);
}

.dark {
  --app-bg: 240 8% 5%;
  --panel-bg: 240 7% 7%;
  --panel-subtle: 240 6% 9%;
  --panel-raised: 240 6% 11%;

  --text-strong: 0 0% 98%;
  --text-normal: 240 4% 86%;
  --text-muted: 240 4% 61%;

  --line-soft: 240 5% 15%;
  --line-strong: 240 5% 23%;

  --interactive: 0 0% 96%;
  --interactive-hover: 0 0% 86%;
}
```

---

# 22. P1：Typed API Error，禁止直接显示 FastAPI 原始 JSON

当前：

```ts
throw new Error(
  `${resp.status}: ${text}`
);
```

所以用户看到：

```text
404: {"detail":"Not Found"}
```

新增：

```ts
export class ApiError extends Error {
  constructor(
    public status: number,
    public endpoint: string,
    public detail: string,
    public requestId?: string,
  ) {
    super(detail);
  }

  get userMessage(): string {
    if (this.status === 404) {
      return "The requested resource was not found.";
    }

    if (this.status === 409) {
      return this.detail;
    }

    if (this.status >= 500) {
      return "PaperForge encountered a server error.";
    }

    return this.detail;
  }
}


async function parseError(
  response: Response,
  endpoint: string,
): Promise<ApiError> {
  let detail = response.statusText;

  try {
    const payload = await response.json();

    if (typeof payload?.detail === "string") {
      detail = payload.detail;
    } else if (payload?.detail) {
      detail = JSON.stringify(payload.detail);
    }
  } catch {
    const text = await response.text();
    if (text) detail = text;
  }

  return new ApiError(
    response.status,
    endpoint,
    detail,
    response.headers.get("x-request-id") ?? undefined,
  );
}


async function getJson<T>(
  path: string,
): Promise<T> {
  const response = await fetch(buildUrl(path));

  if (!response.ok) {
    throw await parseError(response, path);
  }

  return response.json() as Promise<T>;
}
```

---

# 23. P1：Tasks 模型目前是“写了 CRUD，但主流程没用”

仓库已经有：

```text
POST   /api/runs/{run_id}/tasks
GET    /api/runs/{run_id}/tasks
PATCH  /api/runs/{run_id}/tasks/{task_id}
DELETE /api/runs/{run_id}/tasks/{task_id}
```

但 Orchestrator 仍把：

```text
status
phase
```

直接写在 Run 上。

当前主流程没有：

- 创建 task；
- 更新 task phase；
- 关联 event.task_id；
- 前端 task timeline；
- task retry；
- task resume；
- 一个 Run 多任务。

所以 Tasks 目前是孤立 CRUD。

需要二选一：

### 方案 A：MVP 删除 Task 抽象

```text
Run = 一次产品化工作流
```

减少复杂度。

### 方案 B：正式启用 Task

```text
Run = conversation
Task = one productization attempt
Revision = one workspace version
```

推荐长期采用 B：

```text
Run
 ├── Messages
 ├── Task #1: Productize paper
 │    ├── phase
 │    ├── artifacts
 │    ├── revisions
 │    └── events
 └── Task #2: Revise UI
      ├── phase
      ├── artifacts
      └── events
```

---

# 24. 当前已经修复的内容

为了避免重复改错，以下问题在当前 main 中已经有明显修复，不应继续按旧版本方案处理。

---

## 24.1 ProductPlanner 已经注入 capability card

当前已经包含：

```python
"capability_cards": cards,
"product_candidates":
    build_single_paper_candidates(cards),
```

这部分不再是“只传 card ID”。

接下来应优化的是：

- evidence page reference；
- candidate 去重；
- feasibility scoring；
- product constraint；
- user confirmation。

---

## 24.2 Generator 已加入安全约束

当前已有：

```text
BUSINESS_FILES
ALLOWED_DEPENDENCIES
path traversal validator
content size limit
SAFE_SCRIPTS
temporary directory
atomic swap
```

这部分基础安全已经比之前完整。

后续问题变成：

- 只允许 3 个文件限制了复杂产品；
- 无法生成多组件目录；
- 修复器只能修改同样 3 个文件；
- 模板能力决定上限；
- 缺少 AST patch；
- 缺少 workspace revision。

---

## 24.3 BuildRunner 的 `time_ns()` 已修复

当前已经改为：

```python
uuid.uuid4().hex[:12]
```

并且 Docker SDK 调用已经用：

```python
asyncio.to_thread(...)
```

不应再把旧的 `time_ns()` 当作当前 bug。

---

## 24.4 Verifier 已经执行 typecheck、lint、build

当前已有：

```text
npx tsc --noEmit
npm run lint
Docker/local build
security scan
repair function
```

当前未完成的是：

- repair function 没有接入 tool；
- 没有真正浏览器运行测试；
- 没有 console/network 检查；
- PRD coverage 仍是关键词匹配；
- 没有 Playwright trace/screenshot；
- repair 只允许 3 个业务文件。

---

## 24.5 SSE 后端已明显改善

当前已有：

```text
persist first
SQLite monotonic seq
database replay
upper-bound snapshot
live queue dedup
heartbeat
Last-Event-ID
```

当前主要缺口已经转移到前端：

```text
没有传 after_seq
重复 hydrate
effect 反复重连
/state cursor 仍取内存
```

---

# 25. 测试为何没有发现这次 404

当前前端 `package.json` 有：

```text
Vitest
Testing Library
```

但没有 Playwright。

因此目前缺少真正验证：

```text
启动 backend
启动 frontend
创建 run
点击 sidebar run
浏览器打开 /runs/{id}
等待 workspace
断言没有 404
```

API 单测即使覆盖了：

```text
POST /api/approvals/{id}/resolve
```

也无法发现前端实际调用的是缺失的：

```text
GET /api/approvals
```

---

# 26. 必须补充的测试

## 26.1 Approvals API 契约测试

```python
def test_list_approvals_returns_frontend_shape(
    client,
    storage,
):
    run = storage.create_run(
        "run_test",
        "Test",
    )

    created = storage.create_approval(
        run_id=run["id"],
        tool_name="generate_nextjs_app",
        args={"prd_id": "prd_1"},
    )

    response = client.get(
        "/api/approvals",
        params={
            "run_id": run["id"],
            "status": "pending",
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload == [
        {
            "approval_id": created["id"],
            "run_id": run["id"],
            "tool": "generate_nextjs_app",
            "args": {
                "prd_id": "prd_1",
            },
            "status": "pending",
            "created_at": created["created_at"],
            "resolved_at": None,
        }
    ]
```

---

## 26.2 Run state 契约测试

```python
def test_run_state_is_hydratable(
    client,
    storage,
):
    run = storage.create_run(
        "run_state",
        "State",
    )

    storage.add_message(
        run_id=run["id"],
        role="user",
        content="hello",
    )

    storage.create_approval(
        run_id=run["id"],
        tool_name="run_in_sandbox",
        args={},
    )

    response = client.get(
        f"/api/runs/{run['id']}/state"
    )

    assert response.status_code == 200

    state = response.json()

    assert state["run"]["id"] == run["id"]
    assert isinstance(state["messages"], list)
    assert isinstance(state["artifacts"], list)
    assert isinstance(state["pending_approvals"], list)
    assert isinstance(state["event_cursor"], int)

    approval = state["pending_approvals"][0]

    assert "approval_id" in approval
    assert "tool" in approval
    assert "id" not in approval
    assert "tool_name" not in approval
```

---

## 26.3 Browser E2E

安装：

```bash
npm install -D @playwright/test
npx playwright install chromium
```

测试：

```ts
import {
  expect,
  test,
} from "@playwright/test";

test(
  "new run opens without a workspace 404",
  async ({ page }) => {
    await page.goto("/");

    await page
      .getByRole(
        "button",
        { name: /new run/i },
      )
      .click();

    await expect(page).toHaveURL(
      /\/runs\/run_/,
    );

    await expect(
      page.getByText(
        /404.*not found/i,
      )
    ).toHaveCount(0);

    await expect(
      page.getByPlaceholder(
        /ask paperforge/i,
      )
    ).toBeVisible();

    await expect(
      page.getByRole(
        "tab",
        { name: /preview/i },
      )
    ).toBeVisible();
  }
);
```

---

# 27. 推荐实施顺序

## PR-01：修复页面打不开

文件：

```text
api/routes/approvals.py
api/routes/runs.py
web/lib/api.ts
web/app/runs/[id]/page.tsx
web/components/ChatPanel.tsx
```

内容：

```text
补 GET approvals
统一 Approval DTO
/state 返回完整一致结构
Run 页面只请求 /state
SSE 使用 cursor
修复 currentRun effect 重连
typed ApiError
```

验收：

```text
创建 Run 后可打开
旧 Run 可打开
刷新可打开
无审批也可打开
有审批可恢复
后端重启后可恢复事件
```

---

## PR-02：状态与取消正确性

内容：

```text
cancelled 状态
CancelledError 处理
approval expired
run.updated event
sidebar 实时同步
latest sandbox
DB event cursor
```

---

## PR-03：可迭代 Agent 工作流

内容：

```text
移除单向 phase gate
artifact prerequisites
repair_app tool
restart_sandbox tool
stop_sandbox 可调用
preview 后继续修改
done 后可开启新 task
```

---

## PR-04：统一 Workspace 和 Sandbox

内容：

```text
App artifact 作为代码所有者
统一 WorkspaceService
移除重复文件实现
修复目录操作
请求体大小限制
app_artifact_id 启动 sandbox
共享 SandboxManager
```

---

## PR-05：真实 Preview 和 Test

内容：

```text
WebSocket/HMR gateway
Playwright smoke test
console error
failed requests
screenshots
trace
repair history
```

---

## PR-06：UI 工作台重做

内容：

```text
顶部栏
选中 Run 状态
三栏布局
可隐藏 Workbench
真实 Changes
真实 Tests
统一 toast
dark Monaco
错误不卸载整个页面
状态动画
运行进度
```

---

## PR-07：论文解析与产品质量

内容：

```text
Page-aware chunks
Map-Reduce evidence
页码引用
实验/限制抽取
产品候选打分
用户确认
PRD revision
```

---

# 28. 最终验收标准

## 页面可靠性

```text
[ ] 任意合法 Run URL 均可打开
[ ] 可选接口失败不会导致整个页面白屏
[ ] 错误显示友好信息和 Retry
[ ] 刷新后消息、artifact、approval、sandbox 能恢复
```

## 实时交互

```text
[ ] 流式消息不需要刷新
[ ] SSE 不重复 delta
[ ] 状态变化不反复重连
[ ] 断线后从 cursor 恢复
[ ] backend restart 后历史可恢复
```

## Agent 工作流

```text
[ ] 预览后仍可继续修改
[ ] build 失败自动进入 repair
[ ] repair 后重新 verify
[ ] 可停止和重启 sandbox
[ ] 用户拒绝审批后状态正确
[ ] done 不锁死整个 Run
```

## 代码工作区

```text
[ ] 未启动 sandbox 也能浏览代码
[ ] 可新建目录
[ ] 大文件写入被限制
[ ] 有 dirty/saving/saved/error 状态
[ ] Changes 显示真实 diff
[ ] 可恢复 checkpoint
```

## Preview/Test

```text
[ ] Next.js HMR 正常
[ ] iframe 路由和资源正常
[ ] browser smoke test
[ ] console error 可见
[ ] network failure 可见
[ ] trace/screenshot 可下载
```

## UI

```text
[ ] 当前 Run 有选中态
[ ] Sidebar 标题实时更新
[ ] 没有大面积无意义空白
[ ] 工作区可在 Chat/Split/Workbench 切换
[ ] dark mode 全局一致
[ ] 所有失败操作有用户反馈
```

---

# 29. 最重要的判断

当前项目已经不再是“完全没有实现”，而是进入了一个更典型、也更危险的阶段：

```text
组件和接口数量看起来很多
          ≠
端到端链路真的闭环
```

当前最核心的问题是：

```text
后端已有 /state
前端却仍然多请求水合

后端已有持久化 SSE
前端却没有使用 cursor

Verifier 已有 repair 函数
Orchestrator 却没有调用

stop_sandbox 已有 handler
phase gate 却从不允许它

App API 已经存在
Code Editor 却只依赖 sandbox

Tasks CRUD 已经存在
主流程却完全不创建 task

审批写入了数据库
等待机制却只存在内存中
```

所以接下来不应该继续堆更多页面和卡片，而应该优先完成：

```text
契约统一
单一状态来源
可恢复任务
可逆工作流
真实预览
真实浏览器测试
真实文件 diff
```

先修 PR-01，截图中的 404 就会消失；再完成 PR-02 和 PR-03，PaperForge 才会从“看起来像一个 Agent 产品”变成“真正能够反复生成、验证、修改和预览的 Agent 工作台”。
