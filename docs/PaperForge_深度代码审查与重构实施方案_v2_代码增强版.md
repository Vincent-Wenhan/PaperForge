# PaperForge 深度代码审查与重构实施方案（V2 · 代码增强版）

> 复审日期：2026-07-14  
> 复审对象：`Vincent-Wenhan/PaperForge` 当前 `main` 分支  
> 本版本在原方案基础上重新检查了 Orchestrator、Tools、Parser、Planner、Generator、Verifier、BuildRunner、Sandbox、Storage、SSE、Composer、ChatPanel、PreviewPanel 与文件 API，并新增大量可直接拆成 PR 的代码。  
> **阅读规则：第九至第十五部分是对当前代码的第二轮复审；若与前文旧判断冲突，以后文为准。**

## V2 最重要的新发现

- Docker 构建器调用了不存在的 `asyncio event loop.time_ns()`，真实 Docker build 路径存在确定性异常。
- 单论文 Planner 虽然读取 capability card，但没有把内容放入 prompt，论文能力仍然丢失。
- `needs_more_input`、验证失败、preview health check 失败仍可能返回 `ok=True`，导致错误 phase。
- SSE 写入 SQLite 但 replay 仍只读内存；后端重启后 seq 会从 1 重新开始。
- ChatPanel 依赖整个 `currentRun` 注册 SSE，状态更新会导致反复重连和重新水合。
- Composer 在 Ctrl/Cmd+Enter 时可能触发两次发送，普通文件附件仍只停留在本地 UI。
- Generator 的业务文件白名单、依赖白名单和安全 scripts 目前都没有被强制执行。

---

> 审查对象：`Vincent-Wenhan/PaperForge` 当前 `main` 分支  
> 目标：把 PaperForge 从“能够演示若干步骤的原型”升级为“论文驱动、可连续迭代、可真实运行的 AI 产品构建工作台”。  
> 说明：本方案基于 2026-07-14 读取到的仓库代码；后续分支变更可能使行号轻微漂移。

---

## 1. 结论先行

PaperForge 当前最主要的问题并不是“UI 不够像 ChatGPT”，而是以下四条产品闭环没有真正建立：

1. **论文信息没有稳定进入最终产品生成上下文。** 单论文路径中虽然读取了 capability card，却没有把 card 内容传给 ProductPlanner，导致 PRD 和生成产品容易脱离论文。
2. **运行状态不是事实状态。** 规划需要补充信息、构建失败、沙箱未启动成功等情况，仍可能推进到 `planned / verified / preview_ready`。
3. **生成流程是单向流水线，而不是 Coding Agent 循环。** 到 `preview_ready` 后只能 `finish`，用户再说“修改页面”“修复构建”“重启预览”时，后端工具门禁反而不允许执行这些操作。
4. **UI 展示的是推断状态，而非可恢复、可追溯的任务状态。** SSE、水合、消息 ID、预览代理、附件上传等接口没有完全闭环，导致刷新后重复/丢失、假进度、预览不刷新、入口看似可用但实际无效。

因此，不建议先大规模重画页面。正确顺序应当是：

```text
P0 运行正确性
  → P1 Agent 生成—验证—修复闭环
  → P2 ChatGPT/Codex 风格工作台 UI
  → P3 质量、性能、安全与评测
```

---

## 2. 当前架构简图与根因

当前主链路大致为：

```text
PDF
  ↓
PaperParser
  ↓
Capability Card
  ↓
Composer（多论文可选）
  ↓
ProductPlanner → PRD
  ↓
NextjsGenerator → 一次性文件 Manifest
  ↓
Verifier → Build Report
  ↓
DockerSandbox → Preview
```

前端大致为：

```text
Run Sidebar
   +
ChatPanel  ← SSE events
   +
PreviewPanel（preview / files / artifacts / console / verification）
```

这个结构作为 MVP 是合理的，但代码实现把“阶段”当成了不可逆状态机，把“工具执行成功”简化成一个 `ok: bool`，又把“构建、运行、预览、消息流”分别维护在多个松散状态里。最终出现：

- 阶段看起来完成，但真实产物不存在；
- 有错误报告，但 Agent 无法再编辑代码；
- 前端展示了动作按钮，但后端没有对应可执行路径；
- 预览、消息、任务进度无法从同一个事实源恢复。

---

# 第一部分：代码级问题清单

## 3. P0：会直接破坏产品效果或造成错误状态的问题

### 3.1 单论文规划丢失 capability card 内容

**位置**：[`paperforge/agents/product_planner.py`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/paperforge/agents/product_planner.py#L68-L86)

代码先把 card 文件读入 `cards`，但构造 `source_data` 时只保留了 ID：

```python
cards.append(card)

source_data = {
    "composition_id": f"single_{card_ids[0]}",
    "source_cards": list(card_ids),
    "product_candidates": [],
}
```

`cards` 变量之后没有进入 prompt。也就是说，单论文最重要的论文方法、输入输出、限制、可产品化能力，并未真正进入 PRD 生成。

**影响**

- PRD 容易变成通用模板；
- 产品功能与论文方法弱相关；
- Generator 再强也只能基于一个信息贫乏的 PRD 生成；
- 用户主观上会感觉“项目没有理解论文”。

**立即修复**

```python
source_data = {
    "composition_id": f"single_{card_ids[0]}",
    "source_cards": list(card_ids),
    "capability_cards": cards,
    "product_candidates": [
        candidate
        for card in cards
        for candidate in card.get("product_candidates", [])
    ],
}
```

更进一步，card 中每条关键结论应带论文页码或证据片段：

```python
class Evidence(BaseModel):
    paper_id: str
    page: int | None = None
    section: str | None = None
    quote: str
    confidence: float

class Capability(BaseModel):
    name: str
    description: str
    inputs: list[str]
    outputs: list[str]
    constraints: list[str]
    evidence: list[Evidence]
```

**验收标准**

- 单论文与多论文两条路径都能在 PRD artifact 中追踪到 capability card ID；
- PRD 的核心功能至少有一条论文证据引用；
- 对同一论文运行 3 次，产品方向可以变化，但不能脱离论文核心能力。

---

### 3.2 `needs_more_input` 被当成规划成功，错误推进到 `PLANNED`

**位置**：[`paperforge/orchestrator/tools.py`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/paperforge/orchestrator/tools.py#L275-L330)、[`loop.py`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/paperforge/orchestrator/loop.py#L213-L229)

当前 planner 需要用户补充信息时返回：

```python
ToolResult(
    ok=True,
    tool="plan_product",
    data={"needs_more_input": True, "questions": questions},
)
```

而 Orchestrator 只判断 `ok`，因此仍会把阶段推进为 `PLANNED`。此时实际上没有保存 PRD artifact。

**修改方式：区分成功、失败、阻塞**

```python
from enum import Enum

class ToolOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"

class ToolResult(BaseModel):
    tool: str
    outcome: ToolOutcome
    data: dict = Field(default_factory=dict)
    error: str | None = None
    artifact_id: str | None = None
    summary: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome == ToolOutcome.SUCCEEDED
```

Planner 缺信息时：

```python
return ToolResult(
    tool="plan_product",
    outcome=ToolOutcome.BLOCKED,
    data={
        "reason": "needs_user_input",
        "questions": questions,
    },
    summary="Waiting for product requirements.",
)
```

状态推进只接受 `SUCCEEDED`：

```python
if result.outcome == ToolOutcome.SUCCEEDED:
    await transition_after_success(...)
elif result.outcome == ToolOutcome.BLOCKED:
    await task_store.mark_waiting_for_input(task_id, result.data)
```

**UI 对应行为**

不要把问题输出为普通助手段落，而应渲染为结构化 clarification card：

```text
Before I build this, choose one:
○ Research demo
○ General user product
○ Developer API / SDK

Need a real model connection?
○ Mock first
○ Real API now
```

用户回答后恢复同一个 task，而不是创建一条割裂的新流水线。

---

### 3.3 验证失败仍然进入 `VERIFIED`

**位置**：[`paperforge/orchestrator/tools.py`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/paperforge/orchestrator/tools.py#L368-L396)

当前 `handle_verify()` 无论 `build_succeeded` 或 `ready_for_preview` 是什么，都返回 `ok=True`：

```python
return ToolResult(
    ok=True,
    tool="verify_app",
    ...
)
```

这会让“Verified”失去含义，也是右侧进度看起来不真实的根本原因之一。

**修复代码**

```python
build_ok = bool(report.get("build_succeeded"))
preview_ok = bool(report.get("ready_for_preview"))
passed = build_ok and preview_ok

return ToolResult(
    tool="verify_app",
    outcome=(
        ToolOutcome.SUCCEEDED
        if passed
        else ToolOutcome.FAILED
    ),
    artifact_id=artifact_id,
    data={"report": report},
    error=None if passed else "Generated app did not pass verification.",
    summary=(
        "Verification passed."
        if passed
        else "Verification failed; repair is required."
    ),
)
```

不过，最终不应在失败后直接结束，而应进入 Repair Loop，见第 7 节。

---

### 3.4 沙箱未就绪仍返回成功并进入 `PREVIEW_READY`

**位置**：[`paperforge/orchestrator/tools.py`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/paperforge/orchestrator/tools.py#L399-L438)

当前健康检查超时后只发送 `sandbox.error`，最终仍返回 `ok=True`。

**修复代码**

```python
sandbox = await manager.start(run_id=run_id, app_path=app_path)

if sandbox.get("status") != "running":
    return ToolResult(
        tool="run_in_sandbox",
        outcome=ToolOutcome.FAILED,
        data={"sandbox": sandbox},
        error=sandbox.get("error", "Sandbox failed to start"),
    )

ready = await manager.wait_for_http_ready(
    sandbox["id"],
    path="/",
    timeout=60,
)

if not ready:
    logs = await manager.tail_logs(sandbox["id"], lines=200)
    await manager.stop(sandbox["id"])
    return ToolResult(
        tool="run_in_sandbox",
        outcome=ToolOutcome.FAILED,
        data={"sandbox_id": sandbox["id"], "logs": logs},
        error="Preview server did not become HTTP-ready.",
    )

preview_url = preview_gateway.url_for(sandbox["id"])
await ctx.emit.preview_ready(sandbox["id"], preview_url)
return ToolResult(
    tool="run_in_sandbox",
    outcome=ToolOutcome.SUCCEEDED,
    data={"sandbox_id": sandbox["id"], "preview_url": preview_url},
)
```

健康检查要验证 HTTP 200/可接受状态以及页面内容，而不是只检查 TCP 端口。

---

### 3.5 `preview_ready` 后无法继续修改，Quick Actions 与后端能力冲突

**位置**：[`paperforge/orchestrator/loop.py`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/paperforge/orchestrator/loop.py#L49-L71)、[`web/components/Composer.tsx`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/web/components/Composer.tsx)

当前状态门禁：

```python
RunPhase.PREVIEW_READY: {"finish"}
```

但前端同时提供：

- Revise PRD
- Fix build
- Restart preview

因此这些按钮发送文字后，Agent 即便理解意图，也没有权限调用生成、验证、沙箱或编辑工具。

此外，`stop_sandbox` 已注册为工具，但没有出现在任何阶段的 allowed tools 中。

**不要继续扩展线性阶段表。改为“前置条件 + 任务状态”模型。**

```python
TOOL_REQUIREMENTS = {
    "parse_paper": set(),
    "plan_product": {"capability_card"},
    "generate_nextjs_app": {"prd"},
    "read_file": {"workspace"},
    "apply_patch": {"workspace"},
    "verify_app": {"workspace"},
    "run_in_sandbox": {"verified_workspace"},
    "restart_sandbox": {"workspace"},
}

async def validate_tool_requirements(
    tool_name: str,
    run_id: str,
    storage: Storage,
) -> None:
    available = set(storage.list_latest_artifact_types(run_id))
    missing = TOOL_REQUIREMENTS[tool_name] - available
    if missing:
        raise MissingPrerequisite(tool_name, missing)
```

阶段仍可作为 UI 摘要，但应由任务与 artifact 推导，而不是决定 Agent 永远不能回到前一步：

```text
phase = latest successful major milestone
current_task = the actual action now running
```

例如：

```text
Milestone: Preview ready
Current task: Editing app/page.tsx
```

而不是因为 milestone 已经是 preview ready，就禁止编辑。

---

### 3.6 `finish` 没有真正结束循环

`finish` 工具会返回成功结果，但 `loop.py` 没有对它做 terminal handling，也没有把阶段更新成 `DONE`。模型只能在下一轮再决定输出纯文本。

**修复**

```python
result = await self._execute_tool_call(...)

if call.name == "finish" and result.outcome == ToolOutcome.SUCCEEDED:
    self.storage.update_run_phase(run_id, RunPhase.DONE.value)
    self.storage.update_run_status(run_id, "active")
    await emit.task_phase_changed("done", self.phase.value)
    await emit.run_finished()
    return
```

更推荐删除 `finish` 工具，将“没有下一步 action”作为本次 task 完成条件；Conversation 本身保持可继续。

---

### 3.7 SSE 水合与订阅存在竞态，`event_cursor` 没有被使用

**位置**：[`web/components/ChatPanel.tsx`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/web/components/ChatPanel.tsx)、[`web/lib/api.ts`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/web/lib/api.ts)、[`api/routes/events.py`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/api/routes/events.py)、[`paperforge/orchestrator/events.py`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/paperforge/orchestrator/events.py)

后端 `/state` 已返回 `event_cursor`，注释也说明前端应当水合后使用 `after_seq` 连接，但当前前端：

```ts
api.getRunState(currentRun.id).then(...)
sse.connect(currentRun.id)
```

两者并行发生，且 `SSEClient.connect()` 不带 cursor。

可能产生：

- 水合结果覆盖刚收到的流式 delta；
- 首次连接从 0 重放，产生重复消息或事件；
- 后端重启后内存 history 为空，SQLite 中虽然保存了事件，却没有被用于 replay；
- `_seq` 从内存 0 重新开始，持久事件序号不能形成稳定单调序列；
- 订阅队列满时事件被静默丢弃。

**后端：数据库事件日志成为唯一事实源**

```python
class EventManager:
    def next_seq(self, run_id: str) -> int:
        return self.storage.increment_event_seq(run_id)

    async def broadcast(self, event: Event) -> None:
        event.seq = self.next_seq(event.run_id)
        self.storage.save_run_event(event)
        for queue in self._subscribers[event.run_id]:
            await put_with_backpressure(queue, event)

    def history_after(self, run_id: str, after_seq: int) -> list[Event]:
        return self.storage.list_run_events(
            run_id=run_id,
            after_seq=after_seq,
            limit=2000,
        )
```

**前端：先取得一致性快照，再从 cursor 补齐之后事件**

```ts
useEffect(() => {
  if (!runId) return;
  const abort = new AbortController();
  let client: SSEClient | undefined;

  void (async () => {
    const state = await api.getRunState(runId, abort.signal);
    if (abort.signal.aborted) return;

    useAppStore.getState().hydrateRun(state);

    client = new SSEClient();
    registerRunHandlers(client, runId);
    client.connect(runId, state.event_cursor);
  })();

  return () => {
    abort.abort();
    client?.disconnect();
  };
}, [runId]);
```

```ts
connect(runId: string, afterSeq: number) {
  this.disconnect();
  this.seenSeqs.clear();
  const qs = new URLSearchParams({ after_seq: String(afterSeq) });
  this.es = new EventSource(
    buildUrl(`/api/runs/${runId}/events?${qs}`),
  );
}
```

`handlers` 也应改为 `Map<string, Set<Handler>>`，避免同一事件类型只能注册一个 handler。

---

### 3.8 流式消息与数据库消息不是同一个 ID，且工具调用轮次会产生空消息

**位置**：[`paperforge/orchestrator/loop.py`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/paperforge/orchestrator/loop.py#L360-L412)

当前 `_stream_llm()` 在不知道本轮是否只有 tool calls 时就立即发送 `message.started`，最后即使没有文本也发送空的 `message.completed`。之后数据库又通过 `add_message()` 创建另一个消息记录。

结果可能是：

- 工具调用前出现空助手气泡；
- 流式消息使用 `msg_xxx`，刷新后数据库消息使用另一个 ID；
- 前端无法稳定去重；
- tool call、text、artifact 被拆成无关联的 UI 元素。

**建议改成 Message Parts 模型**

```python
message_id = storage.create_message(
    run_id=run_id,
    role="assistant",
    status="streaming",
)

text_started = False
async for chunk in stream_fn(...):
    if chunk.content:
        if not text_started:
            await emit.message_started(message_id)
            text_started = True
        storage.append_message_text(message_id, chunk.content)
        await emit.message_delta(message_id, chunk.content)

    for tool_call in chunk.tool_calls or []:
        await emit.message_part_created(
            message_id,
            part_type="tool_call",
            payload=tool_call.model_dump(),
        )

storage.complete_message(message_id)
if text_started:
    await emit.message_completed(message_id, full_text)
```

推荐数据结构：

```ts
type MessagePart =
  | { type: "text"; text: string }
  | { type: "tool"; callId: string; name: string; status: TaskStatus }
  | { type: "artifact"; artifactId: string; title: string }
  | { type: "approval"; approvalId: string }
  | { type: "error"; message: string; retryable: boolean };
```

这样可以像 ChatGPT/Codex 一样，在同一条消息内展示文字、工具活动、文件修改和审批。

---

### 3.9 “Attach file” 只显示在 UI，发送时根本没有上传

**位置**：[`web/components/Composer.tsx`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/web/components/Composer.tsx)

`handleAttach()` 把本地 `File` 存进 Zustand，但 `handleSend()` 只提取 `type === "paper"` 的 `paperId`。`type === "file"` 的文件没有上传，也没有进入请求。

**若 MVP 只支持论文 PDF，应直接限定并自动上传为 Paper**

```ts
const handleAttach = async (file: File) => {
  if (file.type !== "application/pdf") {
    toast({
      title: "Only PDF papers are supported in this version",
      variant: "error",
    });
    return;
  }

  const pendingId = crypto.randomUUID();
  addAttachment({
    id: pendingId,
    type: "file",
    name: file.name,
    file,
    status: "uploading",
  });

  try {
    const paper = await api.uploadPaper(file);
    replaceAttachment(pendingId, {
      id: paper.paper_id,
      type: "paper",
      name: paper.title,
      paperId: paper.paper_id,
      status: "ready",
    });
  } catch (error) {
    markAttachmentFailed(pendingId, getErrorMessage(error));
  }
};
```

发送前检查所有附件均为 ready，失败时不要清空用户输入。

**若以后支持代码、图片、数据集**，新增独立 attachment API，不要把所有文件伪装成 paper：

```text
POST /api/attachments
GET  /api/attachments/{id}
POST /api/runs/{run_id}/attachments/{id}
```

---

### 3.10 乐观发送失败后保留“幽灵消息”

当前先清空输入并插入用户消息，API 失败时只 toast，不删除消息、不恢复输入，也没有 retry 状态。

**修复**

```ts
const optimisticId = `local_${crypto.randomUUID()}`;
addMessage({
  id: optimisticId,
  role: "user",
  content,
  status: "sending",
});

try {
  const saved = await api.sendMessage(...);
  reconcileMessageId(optimisticId, saved.message_id);
  markMessageCompleted(saved.message_id);
} catch (error) {
  markMessageFailed(optimisticId, getErrorMessage(error));
  setInput(content);
}
```

失败消息旁边提供 `Retry`，而不是让用户重新输入。

---

### 3.11 切换 Run 时旧 sandbox 可能残留

**位置**：[`web/lib/store.ts`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/web/lib/store.ts)

`setCurrentRun()` 清空 messages、events、artifacts 等，但没有清空 `sandbox`。在新 run 水合完成前，右侧可能暂时显示上一个 run 的预览。

同时：

- resolved approvals 只更新状态，没有从 pending 列表移除；
- `events` 无上限增长；
- `lastSeq` 存在但 SSE 没有真正使用；
- 全部运行数据塞进单个全局 store，不利于并发 run 与缓存。

**立即修复**

```ts
setCurrentRun: (run) => set({
  currentRun: run,
  messages: [],
  events: [],
  sandbox: null,
  pendingApprovals: [],
  artifacts: [],
  attachments: [],
  isRunning: false,
  lastSeq: 0,
}),

resolvePendingApproval: (id) => set((state) => ({
  pendingApprovals: state.pendingApprovals.filter(
    (item) => item.approval_id !== id,
  ),
})),

addEvent: (event) => set((state) => ({
  events: [...state.events.slice(-499), event],
})),
```

中期改为 run-scoped cache：

```ts
type RunViewState = {
  messages: Message[];
  tasks: Task[];
  artifacts: Artifact[];
  sandbox: Sandbox | null;
  lastSeq: number;
};

type Store = {
  activeRunId: string | null;
  runsById: Record<string, RunViewState>;
};
```

---

### 3.12 文件夹创建/重命名接口会被扩展名检查拒绝

**位置**：[`api/routes/files.py`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/api/routes/files.py)

`_resolve_safe()` 对任何路径都执行：

```python
if full_path.suffix.lower() not in ALLOWED_EXTS:
    raise HTTPException(...)
```

而 `create_entry(type="directory")` 与目录重命名也调用同一个函数。`components`、`lib/hooks` 等目录没有扩展名，因此会返回 403。

**重构为路径安全与文件类型校验分离**

```python
def _resolve_inside_workspace(sandbox: dict, value: str) -> Path:
    if not value or "\x00" in value:
        raise HTTPException(400, "Invalid path")

    base = Path(sandbox["app_path"]).resolve()
    target = (base / value).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(403, "Path outside workspace")

    relative_parts = target.relative_to(base).parts
    if any(part in BLOCKED_PARTS for part in relative_parts):
        raise HTTPException(403, "Blocked path segment")
    return target


def _validate_editable_file(path: Path) -> None:
    if path.suffix.lower() not in ALLOWED_EXTS:
        raise HTTPException(403, f"Unsupported file type: {path.suffix}")
```

调用方式：

```python
full_path = _resolve_inside_workspace(sandbox, req.path)
if req.type == "directory":
    full_path.mkdir(parents=True, exist_ok=False)
else:
    _validate_editable_file(full_path)
    if len(req.content.encode("utf-8")) > MAX_FILE_SIZE:
        raise HTTPException(413, "File too large")
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(req.content, encoding="utf-8")
```

还需要限制**新内容**的大小；当前只检查已有文件大小。

前端路径应逐段编码，避免 `#`、`?`、`%` 等字符破坏 URL：

```ts
export function encodePath(path: string) {
  return path
    .split("/")
    .map(encodeURIComponent)
    .join("/");
}
```

---

## 4. P0/P1：预览链路为何不稳定

### 4.1 当前 Preview Proxy 只处理 HTTP，没有 WebSocket/HMR

**位置**：[`api/routes/preview.py`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/api/routes/preview.py)

当前 FastAPI 路由把请求代理到容器端口，但没有 WebSocket upgrade 代理，也没有完整处理 HTML 中的绝对资源路径、redirect、cookie 与 CSP。

Next.js dev server 的 HMR 依赖 WebSocket；页面中的 `/_next/...` 通常按站点根路径解析。把预览挂在：

```text
/api/preview/{sandbox_id}/
```

会带来两个高风险问题：

1. `/_next/...` 可能访问 PaperForge 主站，而不是目标沙箱；
2. HMR WebSocket 无法穿过当前纯 HTTP proxy。

这与“代码保存后预览不实时更新”“需要刷新才变化”的表现高度一致。

### 4.2 推荐方案：每个沙箱独立 hostname，而不是 path prefix

```text
https://{sandbox_id}.preview.paperforge.local
```

容器仍监听 3000，由 Traefik/Caddy/Nginx 动态路由。这样：

- 应用仍认为自己运行在 `/`；
- `/_next/*` 路径天然正确；
- WebSocket/HMR 可直接透传；
- cookie、redirect、asset path 不需要复杂重写；
- iframe 与新窗口访问同一个 URL。

Docker 启动核心配置示例：

```python
hostname = f"{sandbox_id}.preview.{settings.PREVIEW_DOMAIN}"
labels = {
    "traefik.enable": "true",
    f"traefik.http.routers.{sandbox_id}.rule": f"Host(`{hostname}`)",
    f"traefik.http.services.{sandbox_id}.loadbalancer.server.port": "3000",
}

container = docker_client.containers.run(
    image=settings.SANDBOX_IMAGE,
    labels=labels,
    network=settings.PREVIEW_NETWORK,
    detach=True,
    ...,
)
```

前端收到后直接：

```ts
setSandbox({ ...sandbox, previewUrl: event.preview_url });
```

不再自行拼接 `/api/preview/...`。

### 4.3 PreviewPanel 必须监听真实事件刷新

目前文件树主要在 sandbox 改变或手动刷新时重新读取。应监听：

```text
workspace.file.written
workspace.file.deleted
workspace.patch.applied
build.started
build.completed
sandbox.ready
sandbox.restarted
runtime.console
runtime.error
```

```ts
useRunEvent("workspace.changed", () => {
  queryClient.invalidateQueries({ queryKey: ["file-tree", workspaceId] });
});

useRunEvent("sandbox.ready", ({ previewUrl, revision }) => {
  setPreviewRevision(revision);
  setPreviewUrl(previewUrl);
});
```

iframe 刷新不应只靠改变 `key` 粗暴重载；开发模式优先依赖 HMR，构建模式才在 revision 变化时 reload。

---

# 第二部分：Agent 与代码生成重构

## 5. 不要再把 Orchestrator 设计成不可逆流水线

建议把概念拆开：

| 概念 | 含义 | 生命周期 |
|---|---|---|
| Conversation / Run | 用户持续对话与项目上下文 | 长期存在，可多轮继续 |
| Task | 一次明确工作，如“生成应用”“修复构建” | pending → running → waiting/succeeded/failed |
| Step | Task 内的原子步骤 | 可重试、可跳过、可取消 |
| Artifact | PRD、实现计划、测试报告等 | 版本化，不覆盖旧版本 |
| Workspace | 当前代码目录 | 有 revision/snapshot |
| Sandbox | 某个 workspace revision 的运行实例 | starting/running/error/stopped |

推荐任务图：

```text
Ingest paper
   ↓
Extract evidence-backed capability card
   ↓
Clarify product intent ─── waiting_for_user
   ↓
Create PRD + UI contract
   ↓
Create implementation plan
   ↓
Generate / patch workspace
   ↓
Static checks + build
   ↓
Browser smoke tests
   ↓
┌──────── pass ────────→ Start/reload preview
│
└─ fail → Diagnose → Patch → Verify  （有限循环）
```

## 6. 新的 Tool 集合

当前工具粒度太粗，只有“一次性生成完整应用”。要具备 Codex/Claude Code 类能力，至少需要：

### 只读工具

```text
list_artifacts
read_artifact
list_files
read_file
search_code
read_build_report
read_runtime_logs
inspect_page
```

### 写入工具

```text
write_file
apply_patch
create_file
move_file
delete_file
install_dependency（受 allowlist/审批控制）
```

### 执行工具

```text
run_command（命令 allowlist + sandbox）
run_typecheck
run_lint
run_build
run_tests
run_browser_tests
start_sandbox
restart_sandbox
stop_sandbox
```

### 产品层工具

```text
parse_paper
compose_capabilities
plan_product
revise_prd
create_implementation_plan
```

工具不应全部直接暴露给顶层 Planner。可以分角色授权：

```python
ROLE_TOOLS = {
    "paper_analyst": {"parse_paper", "read_artifact"},
    "product_planner": {"read_artifact", "plan_product", "revise_prd"},
    "coding_agent": {
        "list_files", "read_file", "search_code",
        "apply_patch", "write_file", "run_build", "run_tests",
    },
    "qa_agent": {
        "run_browser_tests", "inspect_page", "read_runtime_logs",
    },
}
```

## 7. 实现真正的 Generate → Verify → Repair Loop

当前 Verifier 生成报告后就结束，没有把错误反馈给 Coding Agent。

建议新增显式循环，默认限制尝试次数，同时保存每次修复记录：

```python
async def build_and_repair(
    ctx: WorkflowContext,
    max_attempts: int = 3,
) -> VerificationReport:
    for attempt in range(1, max_attempts + 1):
        await ctx.tasks.start_step("verify", attempt=attempt)
        report = await verifier.verify(ctx.workspace)
        await ctx.artifacts.save_versioned("verification_report", report)

        if report.is_ready:
            await ctx.tasks.succeed_step("verify")
            return report

        diagnosis = await repair_agent.diagnose(
            prd=ctx.latest_prd,
            implementation_plan=ctx.latest_plan,
            file_tree=await ctx.workspace.tree(),
            report=report,
            relevant_files=await select_relevant_files(report),
        )

        patch = await repair_agent.create_patch(diagnosis)
        await ctx.workspace.apply_patch(
            patch,
            expected_revision=ctx.workspace.revision,
        )
        await ctx.events.emit(
            "workspace.patch.applied",
            {"attempt": attempt, "files": patch.changed_files},
        )

    raise RepairExhausted(last_report=report)
```

**关键点**

- 只把相关文件、错误日志和 PRD 条目发给 Repair Agent，不要每轮塞整个仓库；
- patch 应带 `expected_revision`，防止用户编辑和 Agent 修改互相覆盖；
- 每次尝试都生成 snapshot，可一键回退；
- UI 显示“尝试 2/3：修复 TypeScript props 错误”，而不是笼统的 `Verified`。

---

## 8. Generator 从“一次性大 JSON”改为“计划 + 增量文件操作”

### 8.1 当前问题

**位置**：[`paperforge/agents/nextjs_generator.py`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/paperforge/agents/nextjs_generator.py#L120-L145)

当前让模型一次返回包含所有文件内容的 JSON manifest，然后直接写入。这种方式存在：

- 输出越复杂越容易截断或 JSON 失效；
- 无法先读模板现有实现再修改；
- 难以针对单个构建错误做小修复；
- `BUSINESS_FILES` 常量只写在注释/变量中，但写文件时没有强制检查；
- `output_dir / f["path"]` 没有阻止绝对路径或 `../`，存在越界写入风险；
- 模型可任意声明依赖与 scripts，供应链和执行风险较高。

### 8.2 立即加固路径

```python
ALLOWED_GENERATED_FILES = {
    "app/page.tsx",
    "lib/mock-api.ts",
    "lib/real-api.ts",
}


def safe_generated_path(base: Path, relative: str) -> Path:
    if relative not in ALLOWED_GENERATED_FILES:
        raise ValueError(f"Model attempted to write disallowed file: {relative}")

    base = base.resolve()
    target = (base / relative).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError("Generated path escapes workspace") from exc
    return target

for generated in manifest["files"]:
    target = safe_generated_path(output_dir, generated["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generated["content"], encoding="utf-8")
```

### 8.3 依赖 allowlist

```python
ALLOWED_DEPENDENCIES = {
    "next", "react", "react-dom",
    "lucide-react", "zod", "recharts",
    "clsx", "tailwind-merge",
}

requested = set(manifest.get("dependencies", {}))
unknown = requested - ALLOWED_DEPENDENCIES
if unknown:
    raise DependencyApprovalRequired(sorted(unknown))
```

不要允许模型覆盖 `build`、`start` 等核心 scripts。

### 8.4 目标生成方式

```text
1. TemplateSelector 选择模板包
2. Planner 输出 implementation_plan.json
3. Coding Agent 读取模板和相关文件
4. 逐文件 write/apply_patch
5. 每个文件写入后触发 workspace.changed
6. Typecheck/build
7. 自动修复
```

Implementation Plan 示例：

```json
{
  "template": "analysis-workbench",
  "routes": ["/"],
  "components": [
    {"path": "components/upload-zone.tsx", "purpose": "paper input"},
    {"path": "components/result-view.tsx", "purpose": "model result"}
  ],
  "data_contracts": [
    {"name": "AnalyzeRequest", "fields": ["input", "options"]}
  ],
  "acceptance_tests": [
    "User can load a sample",
    "Analyze action renders a non-empty result",
    "Reset restores initial state"
  ]
}
```

## 9. 模板系统要从“一个 lightweight 模板”扩展为产品原型模板包

至少准备：

```text
templates/
  research-demo/
  analysis-workbench/
  document-assistant/
  visualization-dashboard/
  workflow-tool/
  api-playground/
```

每个模板包含：

```text
template.json
app/
components/
lib/mock-api.ts
lib/real-api.ts
examples/
tests/
design-tokens.css
```

Planner 不直接决定页面代码，而先输出 UI contract：

```python
class UIContract(BaseModel):
    product_archetype: Literal[
        "research-demo",
        "dashboard",
        "assistant",
        "workflow",
        "api-playground",
    ]
    primary_user_flow: list[str]
    screens: list[ScreenSpec]
    empty_state: str
    loading_state: str
    error_state: str
    sample_data_strategy: str
    responsive_behavior: str
```

这样生成结果不会总是同一个 dashboard，也不需要让模型从零设计所有基础交互。

---

## 10. PaperParser 需要成为“证据化论文理解”，不能只截取前 80k 字符

**位置**：[`paperforge/agents/paper_parser.py`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/paperforge/agents/paper_parser.py)

当前主要依赖 PyMuPDF 纯文本抽取，并截断固定字符数。问题包括：

- 后半部分、limitations、appendix 可能丢失；
- 表格、图注、架构图信息缺失；
- 多栏 PDF 阅读顺序可能错误；
- 扫描 PDF 无 OCR fallback；
- 整篇一次性 prompt，难以稳定提取证据。

推荐管线：

```text
PDF ingest
  → page/block extraction
  → section detection
  → figure/table/caption index
  → chunk-level structured extraction
  → paper-level synthesis
  → evidence validation
  → capability card
```

核心数据结构：

```python
class PaperChunk(BaseModel):
    chunk_id: str
    page_start: int
    page_end: int
    section: str | None
    text: str
    block_ids: list[str]

class ExtractedClaim(BaseModel):
    claim_type: Literal[
        "problem", "method", "input", "output",
        "dataset", "metric", "limitation", "deployment_requirement"
    ]
    value: str
    evidence_chunk_ids: list[str]
    confidence: float
```

Map-Reduce：

```python
claims = []
for chunk in chunks:
    claims.extend(await extract_claims(chunk))

card = await synthesize_capability_card(
    deduplicate_and_link_evidence(claims)
)
```

产品化阶段应明确区分：

```text
论文明确提供的能力
论文可以合理推导的产品能力
需要额外模型/数据/工程才能实现的能力
仅适合 mock 的部分
```

否则生成器容易把论文实验代码误当成完整产品能力。

---

## 11. Verifier 从静态关键词检查升级为多层验证

**位置**：[`paperforge/agents/verifier.py`](https://github.com/Vincent-Wenhan/PaperForge/blob/main/paperforge/agents/verifier.py)

当前基础 build runner 是有价值的，但仍存在：

- PRD coverage 主要靠关键词是否出现在文件中，注释或未使用字符串也可能误判；
- `type_errors`、`lint_errors` 等字段没有形成完整真实解析；
- mock/real boundary 主要按文件名判断；
- 没有浏览器级交互测试；
- 没有收集页面 console error、failed request、截图；
- 没有自动修复闭环。

推荐分五层：

```text
L1 Workspace integrity
   路径、文件大小、依赖、secret、危险代码

L2 Static quality
   TypeScript、ESLint、imports、unit tests

L3 Build
   deterministic npm ci + next build

L4 Runtime
   HTTP readiness、console errors、network failures

L5 Product acceptance
   Playwright user flows + screenshot/visual checks + PRD requirement mapping
```

Playwright smoke test 示例：

```ts
import { test, expect } from "@playwright/test";

test("primary paper-product flow", async ({ page }) => {
  await page.goto(process.env.PREVIEW_URL!);

  await expect(
    page.getByRole("heading", { level: 1 }),
  ).toBeVisible();

  await page.getByRole("button", { name: /load sample/i }).click();
  await page.getByRole("button", { name: /analyze|run/i }).click();

  await expect(
    page.getByTestId("result-panel"),
  ).toContainText(/\S+/);
});
```

运行时收集：

```ts
const consoleErrors: string[] = [];
const pageErrors: string[] = [];
const failedRequests: string[] = [];

page.on("console", (msg) => {
  if (msg.type() === "error") consoleErrors.push(msg.text());
});
page.on("pageerror", (error) => pageErrors.push(error.message));
page.on("requestfailed", (request) => {
  failedRequests.push(`${request.method()} ${request.url()}`);
});
```

失败时保留：

```text
trace.zip
screenshot.png
browser-console.json
network-failures.json
build.log
```

这些 artifact 既给用户看，也作为 Repair Agent 的输入。Playwright 官方推荐 web-first assertions，并提供 Trace Viewer 追踪失败步骤，适合这里的自动诊断场景。

---

## 12. Build 与 Sandbox 需要确定性、异步化和安全隔离

### 12.1 避免重复安装和重复构建

当前 Verifier build 一次，DockerSandbox 启动时又可能 `npm install + build`。建议：

```text
Workspace revision
  → Build image/artifact once
  → Verification uses same artifact
  → Preview starts from same verified revision
```

至少做到：

- 生成 lockfile；
- 使用 `npm ci` 而不是 `npm install`；
- 用 workspace hash 缓存依赖；
- build 与 preview 关联同一 revision；
- 如果是 dev preview，只在依赖变化时重新 install。

### 12.2 不要在 async 函数中直接运行阻塞 Docker SDK

```python
container = await asyncio.to_thread(
    docker_client.containers.run,
    image,
    command=command,
    ...,
)
```

或将 build/sandbox 执行放入独立 worker（推荐长期方案）：

```text
FastAPI
  → task queue
  → build worker
  → sandbox worker
  → persistent event log
```

### 12.3 沙箱加固

构建环境可以受控联网，运行环境默认不需要公网。运行容器示例：

```python
container = client.containers.run(
    image=runtime_image,
    command=["npm", "run", "dev", "--", "-H", "0.0.0.0"],
    user="1000:1000",
    cap_drop=["ALL"],
    security_opt=["no-new-privileges:true"],
    pids_limit=256,
    mem_limit="1g",
    nano_cpus=1_000_000_000,
    read_only=True,
    tmpfs={
        "/tmp": "rw,noexec,nosuid,size=128m",
        "/app/.next": "rw,nosuid,size=512m",
    },
    volumes={
        workspace_path: {
            "bind": "/app",
            "mode": "rw",
        },
    },
    network=preview_network,
    detach=True,
)
```

注意：要根据 Next dev server 写入需求调整只读挂载；核心原则是最小权限、资源上限、无特权、运行网络与构建网络分离。

### 12.4 多用户部署前必须增加归属校验

当前已审查路由中主要根据 `run_id / sandbox_id / artifact_id` 直接访问资源，未看到统一认证与 tenant ownership middleware。若只在本机单用户运行问题较小；若公开部署，则必须加入：

```python
async def require_owned_run(
    run_id: str,
    user: User = Depends(current_user),
) -> Run:
    run = storage.get_run(run_id)
    if not run or run.user_id != user.id:
        raise HTTPException(404)
    return run
```

并覆盖 run、paper、artifact、workspace、sandbox、download、preview 全部资源。

---

# 第三部分：UI/UX 重构方案

## 13. 设计目标：不是复制外观，而是复用成熟交互模式

建议参考：

- ChatGPT / Claude：清晰对话主轴、低干扰消息动作、附件与 artifact；
- Codex 类工作台：任务活动、文件改动、终端/测试、可继续修改；
- [assistant-ui](https://github.com/assistant-ui/assistant-ui)：流式消息、自动滚动、retry、attachments、tool UI、inline approval 等可组合聊天 primitives；
- [Vercel Chatbot](https://github.com/vercel/chatbot)：Next.js App Router、AI SDK、持久化与 shadcn/Radix 组合；
- [OpenHands](https://github.com/OpenHands/openhands) 与其 [typed event system](https://docs.openhands.dev/sdk/arch/events)：事件即不可变追加日志，action/observation/error 分层；
- [bolt.diy](https://github.com/stackblitz-labs/bolt.diy)：prompt、run、edit、deploy 一体化 coding workspace；
- [LibreChat](https://github.com/danny-avila/LibreChat)：conversation search、artifacts、agents、multi-user auth 等完整产品能力。

不建议直接整体照搬某一个仓库。PaperForge 的差异化是：

```text
论文证据 → 产品定义 → 可运行原型 → 验证与迭代
```

UI 必须围绕这个链路设计。

---

## 14. 推荐整体布局：可折叠三栏工作台

```text
┌──────────────┬───────────────────────────┬──────────────────────────────┐
│ Projects     │ Conversation              │ Workbench                    │
│              │                           │                              │
│ Search       │ User / Assistant          │ Preview | Code | Tests       │
│ New project  │ Structured activity       │ Artifacts | Logs             │
│              │ Clarification / Approval  │                              │
│ Recent       │ Artifact cards            │ File tree + editor           │
│ Pinned       │                           │ Runtime errors               │
│ Papers       │ Sticky composer           │                              │
└──────────────┴───────────────────────────┴──────────────────────────────┘
```

### 左栏：Projects，而不是只列 Run ID

内容：

```text
New project
Search
Pinned
Recent
Archived
Paper library
```

每个项目项显示：

- 标题；
- 最近状态小圆点；
- 最后消息/修改时间；
- 是否有运行中的 task；
- 更多菜单：rename、pin、archive、delete。

避免把内部 `run_id` 当作主要信息展示。

### 中栏：Conversation 是产品主轴

消息按一个统一 timeline 展示：

```text
User message
Assistant text
  └─ Activity group
       ✓ Parsed paper
       ✓ Created capability card
       ◐ Generating UI
       ○ Running tests
  └─ Artifact: Product requirements v2
  └─ Changed files: 4
  └─ Approval card
```

不要把所有原始 event 累积到页面底部的 `AgentActivity`。原始事件是数据层；UI 应把它们聚合成用户可理解的 Task/Step。

### 右栏：Workbench

推荐 tabs：

```text
Preview
Code
Changes
Tests
Artifacts
Logs
```

`Files` 与 `Code` 可合并；`Console` 改名为 `Logs`，区分：

```text
Build
Runtime
Browser
Agent
```

Verification 不要只是一张 JSON 报告，而应拆成：

```text
Build          Passed
Typecheck      Passed
Browser tests  2/3 passed
Runtime        1 console error
PRD coverage   6/7 requirements
```

---

## 15. 工作台核心 React 结构

建议添加 `react-resizable-panels`，实现 Codex 类可调整宽度与折叠：

```tsx
export function ProjectWorkspace() {
  return (
    <div className="h-dvh bg-background text-foreground">
      <ProjectHeader />

      <ResizablePanelGroup
        direction="horizontal"
        className="h-[calc(100dvh-48px)]"
      >
        <ResizablePanel
          id="navigation"
          defaultSize={17}
          minSize={12}
          maxSize={24}
          collapsible
        >
          <ProjectSidebar />
        </ResizablePanel>

        <ResizableHandle withHandle />

        <ResizablePanel
          id="conversation"
          defaultSize={40}
          minSize={28}
        >
          <ConversationThread />
        </ResizablePanel>

        <ResizableHandle withHandle />

        <ResizablePanel
          id="workbench"
          defaultSize={43}
          minSize={28}
          collapsible
        >
          <Workbench />
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
```

窄屏：

```text
< 1024px：隐藏左栏，用 Sheet
< 768px：Conversation / Workbench 切换，而非强塞三栏
```

---

## 16. 消息组件应支持完整交互

当前 `MessageView` 主要是普通 Markdown。建议增加：

### 用户消息动作

```text
Edit
Copy
Branch from here
```

### 助手消息动作

```text
Copy
Retry
Continue
Open artifact
View changes
```

### 代码块

```text
语言标签
Copy
Apply to workspace（仅明确 diff）
Open in editor
```

### 工具活动

默认折叠，只显示一行摘要：

```text
✓ Built and tested the app · 42s · 5 steps
```

展开后：

```text
✓ Read PRD
✓ Updated 4 files
✓ Typecheck
✕ Browser test: result panel not found
✓ Patched result-view.tsx
✓ Browser tests
```

### Streaming 细节

- 不对每个 token 执行 `scrollIntoView({behavior: "smooth"})`，否则容易抖动；
- 只有用户当前接近底部时自动跟随；
- 用户向上滚动后显示“Jump to latest”；
- 每帧批量刷新 delta，避免每个 token 触发全树重渲染。

```ts
const isNearBottom = scrollHeight - scrollTop - clientHeight < 120;
if (isNearBottom) requestAnimationFrame(scrollToBottom);
```

---

## 17. Composer 重构

推荐结构：

```text
[attachment chips]
┌──────────────────────────────────────────────┐
│ Ask PaperForge to build or change something │
│                                              │
│ +  Build mode ▾   Model ▾      Send / Stop  │
└──────────────────────────────────────────────┘
```

模式不要仅靠隐藏 prompt template：

```text
Ask      只解释论文/项目
Plan     只生成方案，不写代码
Build    允许生成和修改代码
Debug    优先读取错误并修复
```

请求中显式传递 mode：

```ts
await api.sendMessage(runId, {
  content,
  mode: selectedMode,
  attachmentIds,
  clientMessageId,
});
```

后端按 mode 选择 tool policy，而不是让 LLM 从一句“Fix build”猜测权限。

Quick Actions 应根据当前事实状态动态出现：

```ts
const actions = deriveActions({
  hasPaper,
  hasPrd,
  hasWorkspace,
  verification,
  sandbox,
});
```

例如构建失败才显示 `Fix build`，沙箱运行中才显示 `Restart preview`。

---

## 18. 预览与代码编辑体验

### Preview toolbar

```text
Refresh | Open in new tab | 375 | 768 | 1280 | Fit | Inspect
```

状态：

```text
Starting…
Ready · revision 18
Rebuilding…
Runtime error
Stopped
```

### Code Editor

需要：

- 多标签页；
- dirty 标记；
- `Ctrl/Cmd + S`；
- 外部/Agent 修改冲突提示；
- diff view；
- Accept / Reject Agent changes；
- 文件创建、重命名、删除使用 Dialog，而不是 `prompt()` / `confirm()`；
- Monaco theme 跟随系统 dark/light，而不是写死 `vs-light`。

Revision 冲突协议：

```http
PUT /api/workspaces/{id}/files/{path}
If-Match: "revision-17"
```

冲突返回：

```http
409 Conflict
{
  "current_revision": 18,
  "message": "File changed by the agent after you opened it."
}
```

前端提供：

```text
Compare changes
Overwrite
Reload
```

---

## 19. 视觉系统：高级感来自层级、密度与反馈，不是大量渐变

推荐继续保持黑白灰、轻边框的 Linear/Codex 风格：

```css
:root {
  --background: 0 0% 100%;
  --foreground: 222 20% 10%;
  --muted: 220 14% 96%;
  --muted-foreground: 220 9% 46%;
  --border: 220 13% 90%;
  --accent: 220 14% 94%;
  --destructive: 0 72% 51%;

  --radius-sm: 6px;
  --radius-md: 9px;
  --radius-lg: 12px;
}

.dark {
  --background: 224 18% 8%;
  --foreground: 210 20% 96%;
  --muted: 223 15% 13%;
  --muted-foreground: 218 10% 63%;
  --border: 222 13% 18%;
  --accent: 222 14% 16%;
}
```

原则：

- 主界面最多 1 个强调色；
- 大部分区域使用透明背景 + border，而不是每层一个卡片；
- 消息宽度与正文排版优先；
- 状态色只用于成功、警告、错误；
- 动画 120–220ms，主要用于 panel、popover、状态切换；
- 不给每个工具步骤加入持续旋转动画；
- skeleton 只用于首次加载，流式过程使用真实 task state。

---

# 第四部分：后端数据与事件模型

## 20. 建议的数据表

### tasks

```sql
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 1,
  parent_task_id TEXT,
  input_json TEXT NOT NULL,
  output_json TEXT,
  error_json TEXT,
  started_at TEXT,
  completed_at TEXT,
  created_at TEXT NOT NULL
);
```

### run_events

```sql
CREATE TABLE run_events (
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  event_id TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (run_id, seq)
);
```

### artifact_revisions

```sql
CREATE TABLE artifact_revisions (
  id TEXT PRIMARY KEY,
  artifact_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  type TEXT NOT NULL,
  revision INTEGER NOT NULL,
  data_json TEXT NOT NULL,
  source_task_id TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (artifact_id, revision)
);
```

### workspace_revisions

```sql
CREATE TABLE workspace_revisions (
  workspace_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  snapshot_path TEXT NOT NULL,
  changed_files_json TEXT NOT NULL,
  source TEXT NOT NULL,
  source_task_id TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (workspace_id, revision)
);
```

## 21. 类型化事件

不要继续用任意 `dict`。建议 Pydantic discriminated union：

```python
class BaseRunEvent(BaseModel):
    event_id: str
    run_id: str
    seq: int
    created_at: datetime

class TaskStarted(BaseRunEvent):
    type: Literal["task.started"] = "task.started"
    task_id: str
    title: str

class TaskProgress(BaseRunEvent):
    type: Literal["task.progress"] = "task.progress"
    task_id: str
    completed_steps: int
    total_steps: int | None
    message: str

class WorkspaceChanged(BaseRunEvent):
    type: Literal["workspace.changed"] = "workspace.changed"
    workspace_id: str
    revision: int
    changed_files: list[str]

class VerificationCompleted(BaseRunEvent):
    type: Literal["verification.completed"] = "verification.completed"
    report_id: str
    passed: bool
```

OpenHands 当前事件设计也强调 immutable、type-safe、append-only log，并区分 action、observation、agent error 与 conversation error。PaperForge 不必照搬框架，但应采用同样的数据原则。

---

# 第五部分：建议的新目录结构

```text
paperforge/
  domain/
    runs.py
    tasks.py
    artifacts.py
    workspaces.py
    events.py

  workflows/
    productize_paper.py
    revise_product.py
    repair_workspace.py
    restart_preview.py

  agents/
    paper_analyst.py
    product_planner.py
    ui_planner.py
    coding_agent.py
    repair_agent.py
    qa_agent.py

  tools/
    paper_tools.py
    artifact_tools.py
    workspace_tools.py
    build_tools.py
    browser_tools.py
    sandbox_tools.py

  execution/
    build_worker.py
    sandbox_manager.py
    command_policy.py
    preview_gateway.py

  infrastructure/
    storage/
    event_store/
    llm/
    docker/

web/
  app/
  components/
    shell/
    conversation/
    workbench/
    tasks/
    artifacts/
    ui/
  features/
    runs/
    messages/
    tasks/
    workspace/
    preview/
  lib/
    api/
    events/
    stores/
```

不要求一次性移动全部代码。先建立新边界，新功能放入新目录；旧模块逐步迁移。

---

# 第六部分：分阶段实施顺序

## Milestone 0：先让现有功能真实可信（P0）

必须完成：

1. 单论文 capability card 正确进入 planner；
2. `blocked / failed / succeeded` 工具结果；
3. verify 与 sandbox 按真实结果返回；
4. 移除不可逆 phase gate，至少允许 preview 后 edit/verify/restart；
5. SSE cursor、数据库 replay、统一 message ID；
6. 附件真实上传；
7. 切 run 清空 sandbox；
8. 文件夹 API 修复；
9. generator 路径越界与依赖限制；
10. Preview 改用支持 WebSocket 的独立 hostname gateway。

**退出标准**

- 刷新页面不会丢失或重复消息；
- 构建失败绝不显示 Verified；
- 沙箱未 ready 绝不显示 Preview ready；
- 用户可在预览后继续说“把标题改为 X”，代码、测试和预览都更新；
- 创建/重命名目录正常；
- PDF 附件真正进入请求。

## Milestone 1：建立 Coding Agent 闭环（P1）

1. Workspace revision/snapshot；
2. read/search/write/apply_patch 工具；
3. implementation plan；
4. build/test/repair loop；
5. Playwright smoke tests；
6. runtime console/network error 收集；
7. artifact versioning；
8. task/step/event 数据模型。

**退出标准**

- 至少一类常见 TS/build 错误能自动修复；
- 用户可查看 Agent 改了哪些文件并回退；
- 生成应用通过确定性的 build + browser flow；
- verification report 能指向具体失败步骤、文件、日志和截图。

## Milestone 2：重构 UI 工作台（P2）

1. 三栏 resizable shell；
2. assistant-ui 风格 message parts；
3. task activity group；
4. inline clarification/approval；
5. Preview/Code/Changes/Tests/Artifacts/Logs；
6. Monaco tabs + diff + conflict handling；
7. 动态 quick actions；
8. dark mode、keyboard shortcuts、command palette；
9. responsive behavior。

**退出标准**

- 用户无需理解内部 Agent 名称即可知道当前在做什么；
- 所有状态都来自 task/event，不靠 artifact 文件名猜测；
- 预览、代码、测试报告可互相跳转；
- 主要操作可用键盘完成；
- 流式输出不抖动、不卡顿、不中断。

## Milestone 3：论文理解与产品质量（P2/P3）

1. 分块解析与证据引用；
2. 图表/图注/表格提取；
3. 模板包；
4. UI contract；
5. PRD requirement → acceptance test 映射；
6. 质量评测数据集；
7. 安全与多用户权限。

---

# 第七部分：建议测试矩阵

## 22. 后端单元测试

```text
planner_single_paper_includes_card_content
planner_blocked_does_not_advance_phase
failed_build_does_not_mark_verified
failed_healthcheck_does_not_mark_preview_ready
finish_terminates_current_task
safe_generated_path_rejects_parent_traversal
create_directory_without_suffix_succeeds
new_file_size_limit_is_enforced
event_seq_survives_backend_restart
history_after_reads_persistent_events
```

## 23. 前端单元/集成测试

```text
hydrate_then_replay_does_not_duplicate_messages
switching_runs_clears_previous_sandbox
file_attachment_is_uploaded_before_send
failed_send_restores_draft_and_shows_retry
resolved_approval_is_removed
quick_actions_follow_actual_state
streaming_message_keeps_stable_id
workspace_event_refreshes_file_tree
```

## 24. E2E 场景

```text
1. Upload a paper → receive capability card
2. Clarification required → answer → PRD generated
3. Generate app → build passes → preview ready
4. Ask to change UI → files patched → preview HMR updates
5. Introduce build error → verifier fails → repair loop fixes it
6. Refresh browser mid-stream → no duplicate/lost messages
7. Stop run → task becomes cancelled, process actually stops
8. Restart preview → old sandbox stops, new revision starts
9. Edit same file from user and agent → conflict dialog appears
10. Backend restart → event stream resumes from persistent cursor
```

---

# 第八部分：具体文件改动索引

| 文件 | 建议修改 |
|---|---|
| `paperforge/agents/product_planner.py` | 修复单论文 card 丢失；引入 evidence-backed input |
| `paperforge/orchestrator/tools.py` | ToolOutcome；真实 verify/sandbox 结果；新增 edit/restart/test tools |
| `paperforge/orchestrator/loop.py` | 去除不可逆 gate；统一消息 ID；terminal handling；task-based execution |
| `paperforge/orchestrator/events.py` | 持久 seq；DB replay；typed events；backpressure |
| `paperforge/agents/nextjs_generator.py` | safe path、文件 allowlist、依赖策略、增量生成 |
| `paperforge/agents/verifier.py` | static/build/runtime/browser/acceptance 五层验证 |
| `paperforge/agents/paper_parser.py` | page/block/chunk/evidence pipeline |
| `paperforge/sandbox/build_runner.py` | `npm ci`、缓存、阻塞调用移出 event loop |
| `paperforge/sandbox/docker_runner.py` | HTTP readiness、日志流、资源限制、安全、revision 对齐 |
| `api/routes/events.py` | `after_seq` 查询持久事件；断线恢复 |
| `api/routes/runs.py` | 原子 snapshot + event cursor；latest sandbox 明确排序 |
| `api/routes/preview.py` | 逐步淘汰 path proxy，改 hostname gateway + WebSocket |
| `api/routes/files.py` | 目录路径修复、内容大小、版本冲突、统一 workspace API |
| `web/lib/api.ts` | after_seq、AbortSignal、路径编码、统一错误类型、真实 attachment API |
| `web/lib/store.ts` | run-scoped state、sandbox reset、bounded events、message reconciliation |
| `web/components/ChatPanel.tsx` | 水合后订阅；message parts；task 聚合；稳定自动滚动 |
| `web/components/Composer.tsx` | 上传状态、mode、失败重试、动态 actions |
| `web/components/PreviewPanel.tsx` | 拆分 monolith；HMR/revision；diff/tests/logs；真实进度 |
| `web/components/MessageView.tsx` | code actions、retry、branch、artifact/tool parts |
| `web/components/AgentActivity.tsx` | 从原始事件列表改为 TaskActivityGroup |

---

# 25. 最终产品应该呈现的体验

用户上传论文后：

```text
PaperForge
✓ Read 12 pages and extracted 8 evidence-backed capabilities

I found two viable product directions:
1. Interactive research demo
2. Dataset analysis workbench

Which direction should I build?
[Research demo] [Analysis workbench]
```

用户选择后：

```text
✓ Product requirements v1
✓ Implementation plan · 7 files
◐ Building the first version
```

右侧实时出现文件，并随 Agent 写入更新。构建失败时：

```text
Build failed
app/page.tsx:84 — Property 'score' does not exist on type Result

◐ Repairing the type mismatch · attempt 1/3
✓ Updated app/page.tsx
✓ Typecheck
✓ Browser smoke test
✓ Preview ready
```

用户继续说：

```text
把结果页做得更像一个医学研究工具，并加一个示例病例。
```

Agent 不会因为已经 `preview_ready` 而拒绝工具，而是：

```text
✓ Updated PRD v2
✓ Changed 3 files
✓ Tests passed
✓ Preview updated · revision 12

[View changes] [Open preview] [Restore revision 11]
```

这才是 PaperForge 应该达到的“ChatGPT 的自然对话 + Codex 的工程执行 + 论文产品化证据链”。

---

# 26. 推荐决策

最值得优先做的不是重写全部项目，也不是先接入更强模型，而是：

```text
1. 修复事实状态与数据传递
2. 把 one-shot generator 变成可读写 workspace 的 coding loop
3. 用浏览器测试和自动修复保证“真的能运行”
4. 再用三栏工作台把这些真实能力清晰呈现出来
```

其中 UI 可以参考成熟开源组件，但 Orchestrator、artifact evidence、workspace revision 和 verification loop 应保留 PaperForge 自己的领域设计。这几部分才是项目真正的技术价值。

---

## 参考项目与文档

1. PaperForge repository: <https://github.com/Vincent-Wenhan/PaperForge>
2. assistant-ui: <https://github.com/assistant-ui/assistant-ui>
3. Vercel Chatbot: <https://github.com/vercel/chatbot>
4. OpenHands: <https://github.com/OpenHands/openhands>
5. OpenHands typed events: <https://docs.openhands.dev/sdk/arch/events>
6. bolt.diy: <https://github.com/stackblitz-labs/bolt.diy>
7. LibreChat: <https://github.com/danny-avila/LibreChat>
8. Playwright best practices: <https://playwright.dev/docs/best-practices>
9. Playwright Trace Viewer: <https://playwright.dev/docs/trace-viewer>
---

# 第九部分：第二轮代码级复审与可直接落地补丁（2026-07-14）

> 本部分基于当前 `main` 分支重新逐文件检查。若本部分与前文的旧结论冲突，以本部分为准。这里不再只描述“应该怎么做”，而是尽量按照现有模块、函数签名和数据结构给出可直接拆分为 PR 的代码。

## 27. 当前版本相对上一轮已经改了什么

重新检查后，当前仓库并非完全停留在上一版，以下内容已经有改进：

1. `api/routes/messages.py` 已经在同一个 Run 有任务运行时返回 HTTP 409，避免 API 层静默替换任务。
2. `paperforge/orchestrator/loop.py` 已经改为只有 `ToolResult.ok=True` 才推进 phase。
3. `/api/runs/{run_id}/state` 已经返回 `event_cursor`。
4. 新增了 `/api/apps/{app_id}/...` 文件接口，目录创建不再强制要求扩展名。
5. `run_events` 已经写入 SQLite，说明代码方向已经意识到事件需要持久化。

但这些改动大多只完成了一半：

- 后端虽然返回 409，前端仍会在运行中通过 Enter 发送，并先插入乐观消息；失败后消息不会回滚。
- phase 虽然只在 `ok=True` 时推进，但 `needs_more_input`、验证失败、沙箱未就绪依然被各自 Tool Handler 包装成 `ok=True`。
- `event_cursor` 虽然返回，前端从未传给 `SSEClient.connect()`。
- 事件虽然写入 SQLite，SSE replay 与 `/state` 读取的仍然是内存 `_history`，后端重启后无法恢复。
- app-based 文件 API 已有，但 `PreviewPanel.tsx` 仍调用 sandbox-based 文件 API，所以用户仍然遇到目录操作失败和“没有 sandbox 就不能编辑代码”的问题。

因此当前状态更准确的描述是：**若干保护性接口已经出现，但核心状态闭环还没有真正接通。**

## 28. 第二轮新增 P0 问题总表

| 优先级 | 文件 | 当前问题 | 直接表现 |
|---|---|---|---|
| P0 | `sandbox/build_runner.py` | 使用不存在的 `event_loop.time_ns()` | Docker 可用时构建器在创建容器前直接异常 |
| P0 | `agents/product_planner.py` | 读取 `cards` 后没有放入 `source_data` | 单论文 PRD 看不到论文 capability 内容 |
| P0 | `orchestrator/tools.py` | `needs_more_input` 返回 `ok=True` | 没生成 PRD也推进到 `planned` |
| P0 | `orchestrator/tools.py` | Verifier 无论报告结果都返回 `ok=True` | build 失败仍推进到 `verified` |
| P0 | `orchestrator/tools.py` | sandbox health check 失败仍返回 `ok=True` | preview 未就绪却推进 `preview_ready` |
| P0 | `orchestrator/events.py` | seq 仅来自内存，重启归零 | SQLite 可能出现同一 run 的重复 seq |
| P0 | `api/routes/events.py` | replay 后不更新 `last_seq` | 连接建立瞬间的事件可能重复消费 |
| P0 | `web/components/ChatPanel.tsx` | effect 依赖整个 `currentRun` | status/phase 更新触发 SSE 反复重连与重新水合 |
| P0 | `web/lib/api.ts` | `seenSeqs` 跨 Run 复用 | 切换 Run 后新 Run 的合法事件可能被丢弃 |
| P0 | `web/components/Composer.tsx` | Enter 与 Ctrl/Cmd+Enter 两个分支可同时触发 | 一次键盘操作可能调用两次 `handleSend()` |
| P0 | `agents/nextjs_generator.py` | `BUSINESS_FILES` 只声明不校验 | LLM 可写模板任意路径，甚至路径穿越 |
| P0 | `agents/nextjs_generator.py` | 模型返回的 scripts/dependencies 直接写 package.json | 构建阶段可能执行非预期脚本与依赖 |
| P1 | `agents/verifier.py` | type/lint 字段永远为空 | UI 显示了不存在的验证能力 |
| P1 | `agents/verifier.py` | PRD coverage 仅做关键词出现检查 | 文案里出现词语也会被误判为功能完成 |
| P1 | `web/components/PreviewPanel.tsx` | running sandbox 被当成 preview ready | 真实页面未响应，进度仍显示完成 |
| P1 | `storage/db.py` | 流式 message id 不入库 | 刷新前后消息身份不同、可能出现重复气泡 |

---

# 第十部分：后端核心补丁

## 29. 先修 `BuildRunner`：当前 Docker build 存在确定性运行错误

当前代码：

```python
container_name = f"paperforge-build-{asyncio.get_event_loop().time_ns()}"
```

标准 asyncio event loop 只有 `time()`，没有 `time_ns()`。这段代码位于 `try` 之外，因此 Docker 能连接成功后会立即抛出 `AttributeError`，并且不会进入后面的 container cleanup。

### 29.1 最小修复

```python
# paperforge/sandbox/build_runner.py
import uuid

container_name = f"paperforge-build-{uuid.uuid4().hex[:12]}"
```

### 29.2 建议直接替换 `_run_in_docker`

Docker SDK 是同步 API。当前 `client.ping()`、`containers.create()`、`container.reload()`、`container.logs()` 都在 async 函数中直接调用，会阻塞 FastAPI event loop。下面版本同时修复：

- `time_ns()` 错误；
- `container` 未初始化导致 finally 覆盖原异常；
- 同步 Docker SDK 阻塞；
- 容器退出状态与日志读取；
- timeout 后容器清理。

```python
# paperforge/sandbox/build_runner.py
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

async def _run_in_docker(
    self,
    app_path: Path,
    result: BuildResult,
    install_timeout: int,
    build_timeout: int,
) -> BuildResult:
    try:
        import docker
        from docker.errors import DockerException
    except ImportError:
        result.environment = "local"
        return await self._run_local(
            app_path, result, install_timeout, build_timeout
        )

    def make_client():
        client = docker.from_env()
        client.ping()
        return client

    try:
        client = await asyncio.to_thread(make_client)
    except DockerException as exc:
        logger.warning("Docker unavailable: %s", exc)
        result.environment = "local"
        return await self._run_local(
            app_path, result, install_timeout, build_timeout
        )

    cfg = get_config()
    container = None
    deadline = time.monotonic() + install_timeout + build_timeout
    container_name = f"paperforge-build-{uuid.uuid4().hex[:12]}"

    try:
        container = await asyncio.to_thread(
            client.containers.create,
            image=cfg.SANDBOX_IMAGE,
            command=[
                "sh",
                "-lc",
                "npm ci --no-audit --no-fund && npm run typecheck && npm run build",
            ],
            volumes={
                str(app_path.resolve()): {
                    "bind": "/workspace",
                    "mode": "rw",
                }
            },
            working_dir="/workspace",
            detach=True,
            name=container_name,
            network_disabled=True,
            mem_limit=cfg.SANDBOX_MEM_LIMIT,
            cpu_quota=cfg.SANDBOX_CPU_QUOTA,
            security_opt=["no-new-privileges:true"],
            cap_drop=["ALL"],
        )
        await asyncio.to_thread(container.start)

        while time.monotonic() < deadline:
            await asyncio.to_thread(container.reload)
            if container.status not in {"created", "running", "restarting"}:
                break
            await asyncio.sleep(0.5)
        else:
            await asyncio.to_thread(container.kill)
            result.errors.append("Docker build timed out")
            return result

        await asyncio.to_thread(container.reload)
        logs = await asyncio.to_thread(container.logs, stdout=True, stderr=True)
        text = logs.decode("utf-8", errors="replace")
        exit_code = int(container.attrs["State"].get("ExitCode") or 1)

        result.exit_code = exit_code
        result.stdout = text
        result.install_succeeded = exit_code == 0
        result.build_succeeded = exit_code == 0
        result.ok = exit_code == 0

        if exit_code != 0:
            result.errors.extend(extract_diagnostics(text, limit=80))
        return result
    except Exception as exc:
        logger.exception("Docker build failed")
        result.errors.append(f"Docker build error: {exc}")
        return result
    finally:
        if container is not None:
            try:
                await asyncio.to_thread(container.remove, force=True)
            except Exception:
                logger.warning("Failed to remove build container", exc_info=True)
```

配套辅助函数：

```python
_ERROR_MARKERS = (
    "error:",
    "failed",
    "module not found",
    "type error",
    "syntaxerror",
)


def extract_diagnostics(logs: str, limit: int = 80) -> list[str]:
    selected = [
        line.strip()
        for line in logs.splitlines()
        if line.strip() and any(m in line.lower() for m in _ERROR_MARKERS)
    ]
    return selected[-limit:] or [logs[-4000:]]
```

### 29.3 不要在 Docker 与本地构建之间静默 fallback

当前 Verifier 发生 Docker 异常时会退回本地构建。开发环境可以 fallback，但报告必须明确记录构建环境，否则在 Windows/macOS 本地构建通过，不等于 Alpine 容器可运行。

建议：

```python
class BuildResult(BaseModel):
    ok: bool = False
    environment: Literal["docker", "local"]
    degraded: bool = False
    fallback_reason: str | None = None
```

生产模式：Docker 不可用直接失败；开发模式才允许 fallback。

```python
if cfg.ENV == "production" and not docker_available:
    return BuildResult(
        ok=False,
        environment="docker",
        errors=["Docker is required in production verification"],
    )
```

## 30. 修复单论文 PRD 输入：真正把 capability card 传给 Planner

当前 `product_planner.py` 中虽然执行了：

```python
cards.append(card)
```

但最后的 `source_data` 只有：

```python
{
    "source_cards": card_ids,
    "product_candidates": [],
}
```

`cards` 变量从未进入 prompt。因此单论文流程中，Planner 只能看到论文 ID，看不到方法、输入输出、限制和证据。

### 30.1 最小可用替换

```python
# paperforge/agents/product_planner.py
else:
    cards: list[dict[str, Any]] = []
    for paper_id in card_ids or []:
        paper = storage.get_paper(paper_id)
        if not paper:
            raise ValueError(f"Paper not found: {paper_id}")

        card_path = paper.get("card_path")
        if not card_path or not Path(card_path).exists():
            raise ValueError(f"Capability card not found for paper: {paper_id}")

        card = json.loads(Path(card_path).read_text(encoding="utf-8"))
        cards.append({
            "paper_id": paper_id,
            "title": paper.get("title"),
            "capability": card,
        })

    source_data = {
        "composition_id": f"single_{card_ids[0]}",
        "source_cards": cards,
        "product_candidates": build_single_paper_candidates(cards),
    }
    source_label = "single-paper"
```

候选种子不应为空：

```python
def build_single_paper_candidates(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in cards:
        capability = item["capability"]
        tasks = capability.get("tasks") or capability.get("capabilities") or []
        for index, task in enumerate(tasks[:4]):
            if isinstance(task, str):
                name, description = task, task
            else:
                name = task.get("name") or task.get("task") or f"Capability {index + 1}"
                description = task.get("description") or task.get("summary") or ""
            candidates.append({
                "candidate_id": f"seed_{index + 1}",
                "name": name,
                "source_paper": item["paper_id"],
                "core_capability": description,
                "evidence": task.get("evidence", []) if isinstance(task, dict) else [],
            })
    return candidates
```

## 31. `needs_more_input` 不能是成功状态

当前 `handle_plan_product()` 对需要用户补充信息的情况返回：

```python
ToolResult(ok=True, data={"needs_more_input": True, ...})
```

Orchestrator 只检查 `ok`，所以 phase 仍然从 `parsed/composed` 推进到 `planned`。

### 31.1 扩展 ToolResult，而不是继续滥用 bool

```python
# paperforge/schemas/tool_result.py
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field

class ToolStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"

class ToolResult(BaseModel):
    tool: str
    status: ToolStatus
    code: str | None = None
    artifact_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    error: str | None = None
    retryable: bool = False
    next_phase: str | None = None
    stop_loop: bool = False

    @property
    def ok(self) -> bool:
        return self.status is ToolStatus.SUCCEEDED
```

为了兼容旧代码，也可以先保留序列化字段 `ok`：

```python
@computed_field
@property
def ok(self) -> bool:
    return self.status == ToolStatus.SUCCEEDED
```

### 31.2 Planner blocked 返回值

```python
if planner_output.get("needs_more_input"):
    return ToolResult(
        tool="plan_product",
        status=ToolStatus.BLOCKED,
        code="NEEDS_USER_INPUT",
        data={"questions": planner_output.get("questions") or []},
        summary="More product constraints are required.",
        stop_loop=True,
    )
```

UI 看到 `status=blocked` 后直接渲染结构化问题卡片，而不是显示一个“工具成功”的绿色状态。

## 32. Verifier 和 Sandbox 必须以真实结果决定 Tool 状态

### 32.1 修复 `handle_verify`

当前无论 `ready_for_preview` 是 true 还是 false，都返回 `ok=True`。

```python
async def handle_verify(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    report = await verify_app(
        app_path=args["app_path"],
        prd_id=args.get("prd_id"),
        llm=ctx.llm,
        storage=ctx.storage,
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
        tool="verify_app",
        status=ToolStatus.SUCCEEDED if ready else ToolStatus.FAILED,
        code=None if ready else "VERIFICATION_FAILED",
        artifact_id=artifact_id,
        data={"report": report},
        summary=(
            f"Verification passed, score={report['overall_score']:.2f}."
            if ready
            else f"Verification failed with {len(report.get('build_errors', []))} build errors."
        ),
        retryable=not ready,
        next_phase="verified" if ready else "generated",
    )
```

验证失败后应保持在 `generated` 或进入 `repairing`，不能进入 `verified`。

### 32.2 修复 `handle_run_sandbox`

```python
async def handle_run_sandbox(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    manager = DockerSandboxManager(storage=ctx.storage)
    sandbox = await manager.start(
        run_id=ctx.run_id,
        app_path=args["app_path"],
    )

    if sandbox.get("status") != "running":
        error = sandbox.get("error") or "Sandbox did not enter running state"
        await ctx.emit.sandbox_error(error)
        return ToolResult(
            tool="run_in_sandbox",
            status=ToolStatus.FAILED,
            code="SANDBOX_START_FAILED",
            error=error,
            retryable=True,
        )

    await ctx.emit.sandbox_started(
        sandbox["id"],
        sandbox.get("container_id") or "",
        sandbox.get("preview_port") or 0,
    )

    ready = await manager.wait_for_ready(sandbox["id"], timeout=60)
    if not ready:
        logs = await manager.get_logs(sandbox["id"], tail=200)
        await ctx.emit.sandbox_error("Preview health check timed out")
        return ToolResult(
            tool="run_in_sandbox",
            status=ToolStatus.FAILED,
            code="PREVIEW_NOT_READY",
            data={"sandbox": sandbox, "logs": logs},
            error="Preview server did not become ready within 60 seconds",
            retryable=True,
        )

    preview_url = f"/api/preview/{sandbox['id']}/"
    await ctx.emit.preview_ready(sandbox["id"], preview_url)
    return ToolResult(
        tool="run_in_sandbox",
        status=ToolStatus.SUCCEEDED,
        data={**sandbox, "preview_url": preview_url},
        next_phase="preview_ready",
    )
```

### 32.3 `DockerSandboxManager.start()` 应在失败时抛异常

当前 Docker 不可用或创建失败时只返回 `status="error"`，上层很容易误判。

```python
if not docker_available():
    self.storage.update_sandbox(sandbox_id, status="error")
    raise RuntimeError("Docker is not available")

try:
    container = await asyncio.to_thread(...)
except Exception as exc:
    self.storage.update_sandbox(sandbox_id, status="error")
    raise RuntimeError(f"Failed to start sandbox: {exc}") from exc
```

## 33. Orchestrator：不要再用“工具名固定推进 phase”

当前 phase transition 写死在：

```python
PHASE_TRANSITIONS = {
    "verify_app": RunPhase.VERIFIED,
    "run_in_sandbox": RunPhase.PREVIEW_READY,
}
```

这无法表达：

- verify 失败后回到 repairing；
- 用户要求修订 PRD；
- preview 后修改代码再验证；
- blocked 等待用户；
- rollback 到上一 revision。

### 33.1 最小改造：由 ToolResult 返回 `next_phase`

```python
async def _apply_tool_result(
    self,
    *,
    result: ToolResult,
    emit: EventEmitter,
    run_id: str,
) -> bool:
    """Apply a tool result. Return True when the loop should stop."""
    if result.next_phase:
        old_phase = self.phase
        self.phase = RunPhase(result.next_phase)
        self.storage.update_run_phase(run_id, self.phase.value)
        await emit.task_phase_changed(
            phase=self.phase.value,
            previous_phase=old_phase.value,
        )

    if result.status == ToolStatus.BLOCKED:
        self.storage.update_run_status(run_id, "waiting_user")
        await emit.run_status_changed("waiting_user", "running")
        return True

    if result.status == ToolStatus.CANCELLED:
        self.storage.update_run_status(run_id, "cancelled")
        return True

    if result.stop_loop:
        self.storage.update_run_status(run_id, "active")
        return True

    return False
```

主循环不再重新 `json.loads(result)` 猜结果：

```python
result = await dispatch_tool(call.name, call.args, ctx)  # 返回 ToolResult 对象
await emit.tool_result(call.name, result.model_dump(), call.id)

should_stop = await self._apply_tool_result(
    result=result,
    emit=emit,
    run_id=run_id,
)
if should_stop:
    await emit.run_finished()
    return
```

### 33.2 `finish` 必须真的结束

```python
async def handle_finish(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    return ToolResult(
        tool="finish",
        status=ToolStatus.SUCCEEDED,
        data={"summary": args.get("summary", "Task completed")},
        summary=args.get("summary", "Task completed"),
        next_phase="done",
        stop_loop=True,
    )
```

### 33.3 Preview 后仍允许迭代

推荐 phase：

```python
class RunPhase(str, Enum):
    INIT = "init"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    GENERATING = "generating"
    VERIFYING = "verifying"
    REPAIRING = "repairing"
    PREVIEWING = "previewing"
    WAITING_USER = "waiting_user"
    DONE = "done"
    ERROR = "error"
```

而不是把 `parsed/composed/planned/generated` 当成不可逆关卡。真正的事实应由 artifacts 决定：是否有 card、是否有 PRD、当前 workspace revision 是否通过验证。

## 34. 生成器安全与确定性：完整替换建议

### 34.1 AppManifest 必须验证路径

```python
# paperforge/schemas/app_manifest.py
from pathlib import PurePosixPath
from pydantic import BaseModel, Field, field_validator, model_validator

BUSINESS_FILES = {
    "app/page.tsx",
    "lib/mock-api.ts",
    "lib/real-api.ts",
}

ALLOWED_DEPENDENCIES = {
    "next",
    "react",
    "react-dom",
    "lucide-react",
    "zod",
    "recharts",
    "date-fns",
}

class AppFile(BaseModel):
    path: str
    content: str
    description: str = ""

    @field_validator("path")
    @classmethod
    def safe_business_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").lstrip("/")
        path = PurePosixPath(normalized)
        if ".." in path.parts:
            raise ValueError("Path traversal is not allowed")
        if normalized not in BUSINESS_FILES:
            raise ValueError(f"LLM may only generate: {sorted(BUSINESS_FILES)}")
        return normalized

    @field_validator("content")
    @classmethod
    def size_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 300_000:
            raise ValueError("Generated file is too large")
        return value

class AppManifest(BaseModel):
    app_id: str
    prd_id: str | None = None
    files: list[AppFile] = Field(default_factory=list)
    dependencies: dict[str, str] = Field(default_factory=dict)
    scripts: dict[str, str] = Field(default_factory=dict)
    mock_adapters: list[str] = Field(default_factory=list)
    real_adapters: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_manifest(self):
        paths = [f.path for f in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("Duplicate generated file path")
        unknown = set(self.dependencies) - ALLOWED_DEPENDENCIES
        if unknown:
            raise ValueError(f"Dependencies are not allowed: {sorted(unknown)}")
        return self
```

### 34.2 永远不要采用模型返回的 npm scripts

当前代码允许：

```python
scripts = manifest.get("scripts") or template_pkg.get("scripts")
```

这意味着模型可把 build 脚本改成任意 shell 命令。应该固定 scripts：

```python
SAFE_SCRIPTS = {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "typecheck": "tsc --noEmit",
    "lint": "next lint",
}

pkg["scripts"] = SAFE_SCRIPTS
```

### 34.3 使用临时目录原子生成

```python
# paperforge/agents/nextjs_generator.py
import os
import tempfile

async def generate_nextjs_app(...):
    final_dir = Path(output_dir).resolve()
    apps_root = storage.apps_dir.resolve()
    final_dir.relative_to(apps_root)  # outside root -> ValueError

    with tempfile.TemporaryDirectory(
        prefix="paperforge-generate-",
        dir=str(apps_root),
    ) as temp_name:
        temp_dir = Path(temp_name)
        shutil.copytree(TEMPLATE_DIR, temp_dir, dirs_exist_ok=True)

        manifest = await request_and_validate_manifest(...)
        for generated in manifest.files:
            target = (temp_dir / generated.path).resolve()
            target.relative_to(temp_dir.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(generated.content, encoding="utf-8")

        write_safe_package_json(temp_dir, manifest)
        validate_workspace_shape(temp_dir)

        if final_dir.exists():
            backup = final_dir.with_name(final_dir.name + ".previous")
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(final_dir, backup)
        os.replace(temp_dir, final_dir)

    return {
        **manifest.model_dump(),
        "output_dir": str(final_dir),
    }
```

### 34.4 不允许 LLM 传入任意 output_dir/app_path

`generate_nextjs_app` 和 `run_in_sandbox` 的工具参数里目前都有文件系统路径。LLM 不应该决定服务器路径。

改成只传 artifact ID：

```python
ToolDefinition(
    name="generate_nextjs_app",
    input_schema={
        "type": "object",
        "properties": {"prd_id": {"type": "string"}},
        "required": ["prd_id"],
    },
)

ToolDefinition(
    name="run_in_sandbox",
    input_schema={
        "type": "object",
        "properties": {"app_artifact_id": {"type": "string"}},
        "required": ["app_artifact_id"],
    },
)
```

后端用 artifact metadata 解析路径，并检查 artifact 属于当前 run。

```python
def resolve_run_app(storage: Storage, run_id: str, artifact_id: str) -> Path:
    artifact = storage.get_artifact(artifact_id)
    if not artifact or artifact.get("run_id") != run_id:
        raise PermissionError("App artifact does not belong to this run")
    if artifact.get("type") != "nextjs_app":
        raise ValueError("Artifact is not a Next.js app")
    path = Path(artifact["metadata"]["app_path"]).resolve()
    path.relative_to(storage.apps_dir.resolve())
    return path
```

## 35. PaperParser：从前 80k 截断改为 page-aware map-reduce

当前实现直接保留 PDF 前 80,000 字符，论文后半部分的实验、局限、失败模式、附录和实现细节可能全部丢失。

### 35.1 页面分块

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class PaperChunk:
    chunk_id: str
    page_start: int
    page_end: int
    text: str


def chunk_pdf_pages(pages: list[str], max_chars: int = 22_000) -> list[PaperChunk]:
    chunks: list[PaperChunk] = []
    current: list[str] = []
    current_size = 0
    start_page = 1

    for page_no, text in enumerate(pages, start=1):
        if current and current_size + len(text) > max_chars:
            chunks.append(PaperChunk(
                chunk_id=f"pages_{start_page}_{page_no - 1}",
                page_start=start_page,
                page_end=page_no - 1,
                text="\n\n".join(current),
            ))
            current = []
            current_size = 0
            start_page = page_no
        current.append(f"[[Page {page_no}]]\n{text}")
        current_size += len(text)

    if current:
        chunks.append(PaperChunk(
            chunk_id=f"pages_{start_page}_{len(pages)}",
            page_start=start_page,
            page_end=len(pages),
            text="\n\n".join(current),
        ))
    return chunks
```

### 35.2 Map：每块提取带证据的事实

```python
class EvidenceItem(BaseModel):
    claim: str
    page_start: int
    page_end: int
    quote: str | None = None
    confidence: float

class ChunkExtraction(BaseModel):
    problem: list[EvidenceItem] = []
    method: list[EvidenceItem] = []
    inputs: list[EvidenceItem] = []
    outputs: list[EvidenceItem] = []
    implementation: list[EvidenceItem] = []
    evaluation: list[EvidenceItem] = []
    limitations: list[EvidenceItem] = []
    product_opportunities: list[EvidenceItem] = []
```

```python
async def parse_chunk(chunk: PaperChunk, llm: LLMClient) -> ChunkExtraction:
    response = await llm.chat(
        model=get_config().PARSER_MODEL,
        messages=[
            Message(role="system", content=load_prompt("paper_chunk_parser")),
            Message(
                role="user",
                content=(
                    f"Pages: {chunk.page_start}-{chunk.page_end}\n"
                    "Extract only claims supported by this chunk.\n\n"
                    + chunk.text
                ),
            ),
        ],
        response_format={"type": "json_object"},
    )
    return ChunkExtraction.model_validate_json(response.content or "{}")
```

### 35.3 Reduce：合并而不是重新凭空总结

```python
async def merge_extractions(
    paper_id: str,
    extractions: list[ChunkExtraction],
    llm: LLMClient,
) -> CapabilityCard:
    evidence_payload = [item.model_dump() for ex in extractions for item in flatten(ex)]
    response = await llm.chat(
        model=get_config().PARSER_MODEL,
        messages=[
            Message(role="system", content=load_prompt("paper_card_reducer")),
            Message(role="user", content=json.dumps({
                "paper_id": paper_id,
                "evidence": evidence_payload,
            }, ensure_ascii=False)),
        ],
        response_format={"type": "json_object"},
    )
    return CapabilityCard.model_validate_json(response.content or "{}")
```

最终 capability card 中每个核心结论应带 `evidence_refs`，后续 Planner 和 UI 都可以追溯到论文页码。

## 36. Verifier：从“关键词扫描”升级为真实分层验证

当前 verifier 的几个关键问题：

- `type_errors`、`lint_errors` 从初始化到返回一直为空；
- `llm` 与 verifier prompt 导入但未使用；
- `extra_features` 永远为空；
- mock/real boundary 仅检查文件名是否包含 `mock` / `real`；
- PRD coverage 只要 feature 名中的任意长单词出现在任意文件中就算覆盖；
- 文件下方还保留了一套未被使用的旧 `run_build()`，形成两套构建逻辑。

### 36.1 统一命令执行器

```python
@dataclass
class CommandResult:
    name: str
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

async def run_command(
    name: str,
    command: list[str],
    cwd: Path,
    timeout: int,
) -> CommandResult:
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise VerificationTimeout(name, timeout)
    return CommandResult(
        name=name,
        command=command,
        exit_code=proc.returncode or 0,
        stdout=out.decode(errors="replace"),
        stderr=err.decode(errors="replace"),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
```

### 36.2 验证流水线

```python
async def verify_app(...):
    install = await run_command(
        "install", ["npm", "ci", "--no-audit", "--no-fund"], app_path, 300
    )
    if not install.ok:
        return VerificationReport.failed("install", install)

    typecheck = await run_command(
        "typecheck", ["npm", "run", "typecheck"], app_path, 120
    )
    lint = await run_command(
        "lint", ["npm", "run", "lint"], app_path, 120
    )
    build = await run_command(
        "build", ["npm", "run", "build"], app_path, 240
    )

    browser = None
    if build.ok:
        browser = await run_browser_smoke(app_path)

    coverage = evaluate_acceptance_criteria(
        prd=load_prd(storage, prd_id),
        browser=browser,
        source_files=collect_files(app_path),
    )

    return VerificationReport(
        build_succeeded=build.ok,
        type_errors=parse_tsc(typecheck.stdout + typecheck.stderr),
        lint_errors=parse_eslint(lint.stdout + lint.stderr),
        browser_errors=browser.console_errors if browser else [],
        network_errors=browser.network_errors if browser else [],
        acceptance_results=coverage,
        ready_for_preview=(
            build.ok
            and typecheck.ok
            and lint.ok
            and browser is not None
            and browser.ok
            and all(x.passed for x in coverage if x.priority == "must")
        ),
    )
```

### 36.3 PRD 必须包含可执行验收标准

```python
class AcceptanceCriterion(BaseModel):
    id: str
    feature_id: str
    priority: Literal["must", "should", "could"]
    description: str
    test_kind: Literal["route", "text", "interaction", "visual", "api"]
    selector: str | None = None
    expected: str | bool | int | float | None = None
```

例如：

```json
{
  "id": "ac_upload_1",
  "feature_id": "paper_upload",
  "priority": "must",
  "description": "用户可以选择 PDF 并看到文件名",
  "test_kind": "interaction",
  "selector": "[data-testid='paper-upload']",
  "expected": true
}
```

### 36.4 Playwright smoke test

```python
async def run_browser_smoke(base_url: str) -> BrowserResult:
    from playwright.async_api import async_playwright

    console_errors: list[str] = []
    network_errors: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda msg: (
            console_errors.append(msg.text) if msg.type == "error" else None
        ))
        page.on("requestfailed", lambda req: network_errors.append(
            f"{req.method} {req.url}: {req.failure}"
        ))

        response = await page.goto(base_url, wait_until="networkidle", timeout=30_000)
        await page.screenshot(path="artifacts/smoke.png", full_page=True)

        result = BrowserResult(
            ok=bool(response and response.ok) and not console_errors,
            status=response.status if response else None,
            title=await page.title(),
            console_errors=console_errors,
            network_errors=network_errors,
        )
        await browser.close()
        return result
```

---

# 第十一部分：可靠事件流与消息模型

## 37. 当前 SSE 的三个竞态

### 37.1 服务端 replay/live 重复

`api/routes/events.py` 当前流程：

1. 先注册 queue；
2. replay 内存 history；
3. 进入 queue live loop；
4. `last_seq` 始终保持初始值。

若连接建立期间事件同时进入 history 和 queue，该事件会在 replay 出现一次、queue 再出现一次。

### 37.2 SQLite 实际没有参与 replay

`EventManager.broadcast()` 会调用 `save_run_event()`，但：

- `get_history()` 只读内存；
- `/state` 的 cursor 也只基于内存 history；
- `_seq` 每次进程启动从 0 开始；
- `run_events` 只有普通索引，没有 `UNIQUE(run_id, seq)`。

所以“事件已经持久化”并不等于“事件可恢复”。

### 37.3 queue 满时静默丢事件

每个 subscriber queue `maxsize=1000`，`QueueFull` 后直接 `pass`。客户端既不知道发生 gap，也不会主动重拉。

## 38. 推荐的 Durable Event Log 实现

### 38.1 数据库约束

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_run_events_seq
ON run_events(run_id, seq);
```

SQLite 迁移前先检查并清理重复 seq。

### 38.2 由数据库分配 seq

不要让 `_seq` 只存在于进程内。

```python
# paperforge/storage/db.py
def append_run_event(
    self,
    *,
    run_id: str,
    event_id: str,
    event_type: str,
    data: dict[str, Any],
    task_id: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with self._lock, self._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM run_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        seq = int(row["max_seq"]) + 1
        conn.execute(
            """INSERT INTO run_events
               (id, run_id, task_id, seq, type, data, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                run_id,
                task_id,
                seq,
                event_type,
                json.dumps(data, ensure_ascii=False),
                now,
            ),
        )
    return {
        "id": event_id,
        "run_id": run_id,
        "task_id": task_id,
        "seq": seq,
        "type": event_type,
        "data": data,
        "created_at": now,
    }
```

### 38.3 Persist first, then broadcast

```python
class EventManager:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._subscribers: dict[str, set[asyncio.Queue[Event]]] = defaultdict(set)

    async def publish(self, event: Event) -> Event:
        row = await asyncio.to_thread(
            self.storage.append_run_event,
            run_id=event.run_id,
            event_id=event.id,
            event_type=event.type,
            data=event.data,
            task_id=event.task_id,
        )
        event.seq = row["seq"]

        for queue in tuple(self._subscribers[event.run_id]):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # 放入显式 gap 信号，强制客户端从数据库恢复。
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(Event(
                        id=f"gap_{uuid.uuid4().hex[:8]}",
                        run_id=event.run_id,
                        type="stream.gap",
                        seq=event.seq,
                        data={"resume_after": event.seq - 1},
                    ))
        return event
```

### 38.4 无竞态 SSE route

关键思路：先注册 queue 捕获新事件，再取数据库上界并 replay 到该上界；之后消费 queue，并跳过已经 replay 的 seq。

```python
@router.get("/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    after_seq: int | None = None,
) -> StreamingResponse:
    storage = get_storage()
    if not storage.get_run(run_id):
        raise HTTPException(404, "Run not found")

    manager = get_event_manager()
    queue = manager.register(run_id)
    cursor = after_seq if after_seq is not None else _last_event_id(request)

    async def generate():
        nonlocal cursor
        try:
            upper_bound = await asyncio.to_thread(storage.get_max_event_seq, run_id)
            rows = await asyncio.to_thread(
                storage.list_run_events,
                run_id,
                cursor,
                5000,
                upper_bound,
            )
            for row in rows:
                if row["seq"] <= cursor:
                    continue
                cursor = row["seq"]
                yield encode_sse(row)

            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue

                if event.seq <= cursor:
                    continue
                if event.type == "stream.gap":
                    yield encode_sse(event.to_dict())
                    break

                cursor = event.seq
                yield encode_sse(event.to_dict())
        finally:
            manager.unregister(run_id, queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
```

```python
def encode_sse(row: dict[str, Any]) -> str:
    envelope = {
        "id": row["id"],
        "seq": row["seq"],
        "run_id": row["run_id"],
        "type": row["type"],
        "ts": row.get("created_at"),
        "payload": row.get("data") or {},
    }
    return (
        f"id: {row['seq']}\n"
        f"event: {row['type']}\n"
        f"data: {json.dumps(envelope, ensure_ascii=False)}\n\n"
    )
```

## 39. 前端水合与 SSE：先 snapshot，再从 cursor 接续

当前 `ChatPanel` 同时启动 `/state` 与 SSE；SSE delta 先到后，`setState({messages: state.messages})` 会把实时内容覆盖。并且 effect 依赖整个 `currentRun`，每次 phase/status 改变都会重新执行 effect。

### 39.1 把连接逻辑移入 `useRunSession`

```tsx
// web/lib/use-run-session.ts
"use client";

import { useEffect } from "react";
import { api, SSEClient } from "@/lib/api";
import { applyRunEvent, useAppStore } from "@/lib/store";

export function useRunSession(runId?: string) {
  useEffect(() => {
    if (!runId) return;

    let disposed = false;
    const sse = new SSEClient();

    async function start() {
      const snapshot = await api.getRunState(runId);
      if (disposed) return;

      const store = useAppStore.getState();
      // 只在当前仍是同一个 run 时应用，避免慢请求污染新 run。
      if (store.currentRun?.id !== runId) return;

      store.hydrateRun(runId, snapshot);

      sse.onAny((event) => {
        const current = useAppStore.getState();
        if (current.currentRun?.id !== runId) return;
        applyRunEvent(event);
      });
      sse.connect(runId, snapshot.event_cursor);
    }

    start().catch((error) => {
      if (!disposed) useAppStore.getState().setConnectionError(String(error));
    });

    return () => {
      disposed = true;
      sse.disconnect();
    };
  }, [runId]); // 注意：只依赖稳定的 runId，不依赖整个 currentRun 对象
}
```

ChatPanel：

```tsx
export function ChatPanel() {
  const runId = useAppStore((s) => s.currentRun?.id);
  useRunSession(runId);
  // 这里只负责渲染，不再注册二十多个 SSE listener。
  ...
}
```

### 39.2 修复 SSEClient 的跨 Run seq 污染

```tsx
export class SSEClient {
  private source: EventSource | null = null;
  private runId: string | null = null;
  private lastSeq = 0;
  private handlers = new Set<(event: RunEvent) => void>();

  onAny(handler: (event: RunEvent) => void) {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  connect(runId: string, afterSeq = 0) {
    this.disconnect();
    this.runId = runId;
    this.lastSeq = afterSeq;

    const params = new URLSearchParams({ after_seq: String(afterSeq) });
    this.source = new EventSource(
      buildUrl(`/api/runs/${runId}/events?${params.toString()}`),
    );

    const knownTypes = [
      "message.started",
      "message.delta",
      "message.completed",
      "message.failed",
      "tool.call",
      "tool.result",
      "artifact.created",
      "approval.requested",
      "approval.resolved",
      "run.started",
      "run.finished",
      "run.error",
      "run.status.changed",
      "task.phase.changed",
      "sandbox.started",
      "sandbox.error",
      "preview.ready",
      "stream.gap",
    ];

    for (const type of knownTypes) {
      this.source.addEventListener(type, (raw) => {
        const event = JSON.parse((raw as MessageEvent).data) as RunEvent;
        if (event.run_id !== this.runId || event.seq <= this.lastSeq) return;
        this.lastSeq = event.seq;
        this.handlers.forEach((handler) => handler(event));
      });
    }
  }

  disconnect() {
    this.source?.close();
    this.source = null;
    this.runId = null;
    this.lastSeq = 0;
  }
}
```

### 39.3 单一 event reducer

不要在 ChatPanel 内手写一长串 listener。统一 reducer 才能保证刷新、replay、live 三种路径行为一致。

```tsx
export function applyRunEvent(event: RunEvent) {
  const store = useAppStore.getState();
  store.setLastSeq(event.seq);

  switch (event.type) {
    case "message.started":
      store.upsertMessage({
        id: event.payload.message_id,
        role: "assistant",
        content: "",
        streaming: true,
        status: "streaming",
      });
      break;
    case "message.delta":
      store.appendMessageDelta(
        event.payload.message_id,
        event.payload.delta ?? "",
      );
      break;
    case "message.completed":
      store.completeMessage(
        event.payload.message_id,
        event.payload.content ?? "",
      );
      break;
    case "artifact.created":
      void api.getArtifact(event.payload.artifact_id).then(store.addArtifact);
      break;
    case "preview.ready":
      store.setPreviewState({
        status: "ready",
        sandboxId: event.payload.sandbox_id,
        url: event.payload.preview_url,
      });
      break;
    case "sandbox.error":
      store.setPreviewState({
        status: "error",
        error: event.payload.error,
      });
      break;
    case "run.status.changed":
      store.updateCurrentRun({ status: event.payload.status });
      break;
    case "task.phase.changed":
      store.updateCurrentRun({ phase: event.payload.phase });
      break;
    case "stream.gap":
      void store.rehydrateCurrentRun();
      break;
  }
}
```

## 40. 流式消息 ID 必须持久化

当前 SSE 中的 `message_id` 是临时 UUID；SQLite `messages.id` 是自增整数，`add_message()` 不能接受外部 ID。刷新后 UI 无法把同一条消息识别为同一条。

### 40.1 数据库迁移

```sql
ALTER TABLE messages ADD COLUMN public_id TEXT;
ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'completed';
ALTER TABLE messages ADD COLUMN parts TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_public_id
ON messages(public_id);
```

### 40.2 开始流式时先创建消息

```python
def create_streaming_message(self, run_id: str, public_id: str) -> None:
    with self._lock, self._conn() as conn:
        conn.execute(
            """INSERT INTO messages
               (public_id, run_id, role, content, status)
               VALUES (?, ?, 'assistant', '', 'streaming')""",
            (public_id, run_id),
        )


def append_message_delta(self, public_id: str, delta: str) -> None:
    with self._lock, self._conn() as conn:
        conn.execute(
            """UPDATE messages
               SET content = COALESCE(content, '') || ?
               WHERE public_id = ?""",
            (delta, public_id),
        )


def complete_message(self, public_id: str, content: str) -> None:
    with self._lock, self._conn() as conn:
        conn.execute(
            "UPDATE messages SET content = ?, status = 'completed' WHERE public_id = ?",
            (content, public_id),
        )
```

为了减少 SQLite 高频写入，可以在内存缓冲 100–250ms 后批量 flush，但 message public ID 必须一开始就入库。

---

# 第十二部分：前端交互与工作台代码

## 41. 修复 Composer 的双发送、运行中发送和假附件

### 41.1 当前键盘逻辑会重复触发

当前：

```tsx
if (e.key === "Enter" && !e.shiftKey && !sending) handleSend();
if ((e.metaKey || e.ctrlKey) && e.key === "Enter") handleSend();
```

按 Ctrl+Enter 时，两个条件都为真。

### 41.2 可直接替换的发送逻辑

```tsx
const submitLock = useRef(false);

const handleSend = async () => {
  const content = input.trim();
  if (!content || sending || isRunning || submitLock.current) return;

  submitLock.current = true;
  setSending(true);

  const optimisticId = crypto.randomUUID();
  addMessage({
    id: optimisticId,
    role: "user",
    content,
    status: "streaming",
  });

  try {
    const paperIds: string[] = [];
    for (const attachment of attachments) {
      if (attachment.type === "paper" && attachment.paperId) {
        paperIds.push(attachment.paperId);
        continue;
      }
      if (attachment.file) {
        if (attachment.file.type !== "application/pdf") {
          throw new Error("PaperForge currently supports PDF attachments only");
        }
        const uploaded = await api.uploadPaper(attachment.file);
        paperIds.push(uploaded.paper_id);
      }
    }

    await api.sendMessage(currentRun.id, content, paperIds);
    useAppStore.getState().completeOptimisticMessage(optimisticId);
    useAppStore.getState().clearAttachments();
    setInput("");
    setIsRunning(true);
  } catch (error) {
    useAppStore.getState().removeMessage(optimisticId);
    setInput(content);
    toast({
      title: "Message was not sent",
      description: error instanceof Error ? error.message : String(error),
      variant: "error",
    });
  } finally {
    submitLock.current = false;
    setSending(false);
  }
};

const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
  if (event.nativeEvent.isComposing) return;
  if (event.key !== "Enter") return;

  const commandEnter = event.metaKey || event.ctrlKey;
  const plainEnter = !event.shiftKey && !event.metaKey && !event.ctrlKey;
  if (!commandEnter && !plainEnter) return;

  event.preventDefault();
  void handleSend();
};
```

Textarea 与 attachment button 也应在运行时禁用，或者明确支持“排队下一条消息”，不能看似可发送、实际返回 409。

```tsx
<textarea disabled={sending || isRunning} ... />
<button disabled={sending || isRunning}>Attach PDF</button>
```

## 42. Store 必须真正按 Run 隔离

当前 `setCurrentRun` 没有清空 sandbox，因此切换 Run 时可能短暂显示旧预览。

```tsx
setCurrentRun: (run) => set({
  currentRun: run,
  messages: [],
  events: [],
  sandbox: null,
  previewState: { status: "idle" },
  pendingApprovals: [],
  artifacts: [],
  attachments: [],
  isRunning: false,
  lastSeq: 0,
  openFiles: [],
  activeFilePath: null,
}),
```

更稳妥的结构是缓存每个 Run 的状态：

```tsx
type RunSession = {
  messages: Message[];
  events: RunEvent[];
  artifacts: Artifact[];
  sandbox: Sandbox | null;
  preview: PreviewState;
  lastSeq: number;
};

type AppState = {
  activeRunId: string | null;
  sessions: Record<string, RunSession>;
};
```

这样从 Run A 切换到 B 再回来，不需要先清空再闪烁加载。

## 43. 代码编辑不应依赖 sandbox

当前 `PreviewPanel` 只有 `sandbox` 才加载文件树，且调用 `/api/files/sandboxes/...`。代码 workspace 本身应该是 artifact，sandbox 只是该 revision 的运行实例。

### 43.1 从 nextjs_app artifact 得到 app ID

```tsx
const appArtifact = useMemo(
  () => [...artifacts].reverse().find((a) => a.type === "nextjs_app"),
  [artifacts],
);
const appId = appArtifact?.id;

useEffect(() => {
  if (!appId) {
    setTree([]);
    return;
  }
  api.listAppTree(appId).then((response) => {
    setTree(buildNestedTree(response.tree ?? []));
  });
}, [appId]);
```

文件读写改为：

```tsx
await api.readAppFile(appId, path);
await api.writeAppFile(appId, path, content);
await api.createAppEntry(appId, entry);
await api.renameAppEntry(appId, path, newPath);
```

这样即使 preview 崩了，用户仍能编辑并修复代码。

### 43.2 sandbox-based `_resolve_safe()` 仍需修复

虽然 app API 已允许目录，但旧 sandbox API 仍对目录调用 `suffix` 白名单。若暂时保留该 API，拆分解析与文件扩展名检查：

```python
def _resolve_safe(sandbox: dict, relative_path: str) -> Path:
    base = Path(sandbox["app_path"]).resolve()
    target = (base / relative_path).resolve()
    target.relative_to(base)
    rel_parts = target.relative_to(base).parts
    if any(part in BLOCKED_PARTS for part in rel_parts):
        raise HTTPException(403, "Blocked path segment")
    return target


def _require_allowed_file(path: Path) -> None:
    if path.suffix.lower() not in ALLOWED_EXTS:
        raise HTTPException(403, f"Unsupported file type: {path.suffix or '(none)'}")
```

只在 read/write/create-file 时调用 `_require_allowed_file()`，目录创建与目录重命名不要调用。

### 43.3 请求体大小也要检查

当前只检查“已有文件”的大小，没有检查即将写入的内容：

```python
def ensure_content_size(content: str) -> None:
    size = len(content.encode("utf-8"))
    if size > MAX_FILE_SIZE:
        raise HTTPException(413, f"File exceeds {MAX_FILE_SIZE} bytes")
```

## 44. Preview 状态要与 sandbox 状态分开

当前：

```tsx
const previewReady = Boolean(sandbox?.id) && sandbox?.status === "running";
```

容器 running 只表示 Docker process 启动，不表示 Next.js 已编译并能返回页面。

```tsx
type PreviewState =
  | { status: "idle" }
  | { status: "starting"; sandboxId: string }
  | { status: "ready"; sandboxId: string; url: string }
  | { status: "error"; sandboxId?: string; error: string };
```

只有收到 `preview.ready` 才显示 complete。`sandbox.error` 或健康检查超时显示明确错误和日志入口。

```tsx
const progress = [
  ...,
  {
    id: "preview",
    label: "Live preview",
    status:
      preview.status === "ready"
        ? "complete"
        : preview.status === "error"
          ? "error"
          : "pending",
  },
];
```

## 45. 支持 HMR 的 Preview Gateway

当前 path-prefix HTTP proxy 无法完整代理 Next.js HMR WebSocket。推荐每个 sandbox 使用独立 hostname：

```text
sandbox_<id>.preview.localhost
```

后端只提供解析：

```python
@router.get("/api/sandboxes/{sandbox_id}/route")
async def get_route(sandbox_id: str):
    sandbox = require_running_sandbox(sandbox_id)
    return {
        "host": f"{sandbox_id}.preview.localhost",
        "upstream": f"http://127.0.0.1:{sandbox['preview_port']}",
    }
```

Caddy 示例：

```caddyfile
*.preview.localhost {
    @sandbox host_regexp sandbox {id:[a-zA-Z0-9_-]+}.preview.localhost
    reverse_proxy 127.0.0.1:{http.reverse_proxy.upstream.port} {
        header_up Host {host}
        header_up Connection {>Connection}
        header_up Upgrade {>Upgrade}
    }
}
```

生产环境建议由 gateway 读取 Redis/数据库中的 `sandbox_id -> port` 映射。这样 WebSocket、静态资源绝对路径、Next.js dev overlay 都不再依赖 path rewrite。

---

# 第十三部分：更接近 ChatGPT / Codex / Claude 的 UI 实现骨架

## 46. UI 不是再添加更多卡片，而是建立统一工作台

推荐结构：

```tsx
// web/app/page.tsx
export default function HomePage() {
  return (
    <RunProvider>
      <div className="h-dvh overflow-hidden bg-background text-foreground">
        <WorkspaceLayout
          navigation={<ProjectSidebar />}
          conversation={<ConversationPane />}
          workbench={<WorkbenchPane />}
        />
      </div>
    </RunProvider>
  );
}
```

### 46.1 可伸缩三栏

建议使用 `react-resizable-panels`：

```tsx
import {
  Panel,
  PanelGroup,
  PanelResizeHandle,
} from "react-resizable-panels";

export function WorkspaceLayout({ navigation, conversation, workbench }: Props) {
  return (
    <PanelGroup direction="horizontal" autoSaveId="paperforge-layout">
      <Panel defaultSize={18} minSize={12} maxSize={28} collapsible>
        {navigation}
      </Panel>
      <PanelResizeHandle className="w-px bg-border hover:bg-ring" />
      <Panel defaultSize={42} minSize={28}>
        {conversation}
      </Panel>
      <PanelResizeHandle className="w-px bg-border hover:bg-ring" />
      <Panel defaultSize={40} minSize={28}>
        {workbench}
      </Panel>
    </PanelGroup>
  );
}
```

窄屏时不要硬塞三栏：conversation 和 workbench 用 tabs/sheet 切换。

## 47. Message Parts，而不是把 Tool 活动和聊天拆成两个世界

```tsx
type MessagePart =
  | { type: "text"; text: string }
  | { type: "reasoning-summary"; text: string }
  | { type: "tool"; callId: string; name: string; state: ToolState; result?: unknown }
  | { type: "artifact"; artifactId: string }
  | { type: "approval"; approvalId: string }
  | { type: "error"; message: string };
```

```tsx
export function AssistantMessage({ message }: { message: Message }) {
  return (
    <article className="group mx-auto w-full max-w-3xl px-5 py-4">
      <div className="space-y-3">
        {message.parts.map((part, index) => {
          switch (part.type) {
            case "text":
              return <Markdown key={index}>{part.text}</Markdown>;
            case "tool":
              return <InlineToolPart key={part.callId} part={part} />;
            case "artifact":
              return <ArtifactPreview key={part.artifactId} id={part.artifactId} />;
            case "approval":
              return <InlineApproval key={part.approvalId} id={part.approvalId} />;
            case "error":
              return <InlineError key={index}>{part.message}</InlineError>;
          }
        })}
      </div>
      <MessageActions message={message} />
    </article>
  );
}
```

Tool 默认只显示一行：

```text
✓ Generated app · 3 files changed · 18.4s
```

展开后再显示 args、logs、artifact、diff。这样更接近 Codex/Claude 的信息密度，而不是把所有 JSON 永久铺开。

## 48. Workbench tabs 应围绕“工作产物”组织

```tsx
const WORKBENCH_TABS = [
  { id: "preview", label: "Preview" },
  { id: "code", label: "Code" },
  { id: "changes", label: "Changes" },
  { id: "tests", label: "Tests" },
  { id: "artifacts", label: "Artifacts" },
  { id: "logs", label: "Logs" },
] as const;
```

其中：

- Preview：页面、viewport、refresh/restart/open；
- Code：文件树、Monaco、dirty 状态；
- Changes：agent 修改前后 diff 与 accept/revert；
- Tests：typecheck/lint/build/browser/acceptance criteria；
- Artifacts：capability、PRD、verification、screenshots；
- Logs：sandbox/build/network/console。

当前单独的 `AgentActivity` 不应占据主要信息层级，可变成 conversation 顶部的 compact timeline 或 workbench 的 task drawer。

## 49. 设计 tokens 与动效

```css
/* web/app/globals.css */
:root {
  --background: 0 0% 100%;
  --foreground: 222 18% 12%;
  --muted: 220 16% 96%;
  --muted-foreground: 220 8% 44%;
  --border: 220 13% 90%;
  --ring: 221 83% 53%;
  --radius: 0.65rem;
  --panel-shadow: 0 1px 2px rgb(0 0 0 / 0.04), 0 12px 36px rgb(0 0 0 / 0.05);
}
```

高级感重点是：

- panel 边界细、留白一致；
- 主聊天最大宽度固定；
- 消息没有大面积彩色气泡；
- tool 活动使用轻量状态与 progressive disclosure；
- streaming cursor、tab 切换、sidebar collapse 使用 120–180ms 动效；
- 不使用大量渐变和持续旋转动画。

```tsx
<motion.div
  initial={{ opacity: 0, y: 4 }}
  animate={{ opacity: 1, y: 0 }}
  transition={{ duration: 0.16, ease: [0.2, 0.8, 0.2, 1] }}
/>
```

建议优先参考以下开源实现方式，而不是复制视觉截图：

- assistant-ui：Thread / Message / Composer / Tool UI / attachments 的运行时模型；
- Vercel Chatbot：Next.js App Router、流式消息和 thread persistence；
- OpenHands：agent event、sandbox、action/observation、任务执行轨迹；
- react-resizable-panels：持久化可伸缩工作台；
- Monaco Editor：代码编辑、markers、diff editor。

---

# 第十四部分：审批、取消与恢复

## 50. 当前 ApprovalRegistry 无法跨进程恢复

当前审批流程：

1. Orchestrator 在内存 registry 注册 `asyncio.Event`；
2. 等待最多 5 分钟；
3. 后端重启后 SQLite 中仍是 pending，但等待它的 task 已不存在；
4. 用户点击同意也无法恢复原 tool call。

不要让一个 HTTP 服务进程中的 coroutine 持有五分钟工作流状态。

### 50.1 推荐暂停任务而不是 await

```python
if tool_requires_approval(call.name):
    approval = storage.create_approval(...)
    storage.save_task_checkpoint(
        task_id=task_id,
        state={
            "messages": serialize_messages(messages),
            "phase": self.phase.value,
            "pending_tool_call": call.model_dump(),
        },
        status="waiting_approval",
    )
    await emit.approval_requested(...)
    return OrchestratorExit.WAITING_APPROVAL
```

审批 endpoint：

```python
@router.post("/{approval_id}/resolve")
async def resolve_approval(approval_id: str, req: ApprovalResolve):
    approval = storage.resolve_approval_once(approval_id, req.approved)
    if req.approved:
        task_manager.resume_from_checkpoint(approval["task_id"])
    else:
        task_manager.resume_with_rejection(approval["task_id"])
    return approval
```

## 51. Cancel 必须产生持久化状态和事件

`asyncio.CancelledError` 在现代 Python 中不应只依赖 `except Exception`。在 Orchestrator 中显式处理：

```python
except asyncio.CancelledError:
    self.storage.update_run_status(run_id, "cancelled")
    await emit.run_status_changed("cancelled", "running")
    await emit.emit("run.cancelled", {"reason": "user_requested"})
    raise
```

RunTaskManager 也应等待取消完成，而不是仅调用 `task.cancel()` 就返回成功：

```python
async def cancel(self, run_id: str) -> bool:
    task = self.tasks.get(run_id)
    if not task or task.done():
        return False
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    return True
```

API route 相应改成 `await task_manager.cancel(run_id)`。

---

# 第十五部分：测试代码与验收标准

## 52. 必须新增的后端回归测试

### 52.1 单论文 card 内容进入 planner prompt

```python
@pytest.mark.asyncio
async def test_single_paper_planner_receives_capability_content(tmp_storage, fake_llm):
    tmp_storage.upsert_paper(
        paper_id="p1",
        title="Paper",
        pdf_path="/tmp/p1.pdf",
        card_path=str(write_json({
            "method": "Diffusion restoration",
            "inputs": ["degraded image"],
        })),
        status="parsed",
    )

    await plan_product(
        user_requirement="Build a demo",
        card_ids=["p1"],
        composition_id=None,
        llm=fake_llm,
        storage=tmp_storage,
    )

    prompt = fake_llm.last_messages[-1].content
    assert "Diffusion restoration" in prompt
    assert "degraded image" in prompt
```

### 52.2 needs_more_input 不推进 phase

```python
@pytest.mark.asyncio
async def test_blocked_planner_does_not_advance_to_planned(orchestrator, storage):
    storage.update_run_phase("run_1", "parsed")
    result = ToolResult(
        tool="plan_product",
        status=ToolStatus.BLOCKED,
        code="NEEDS_USER_INPUT",
        stop_loop=True,
    )

    stopped = await orchestrator._apply_tool_result(
        result=result,
        emit=FakeEmitter(),
        run_id="run_1",
    )

    assert stopped is True
    assert storage.get_run_phase("run_1") == "parsed"
    assert storage.get_run_status("run_1") == "waiting_user"
```

### 52.3 BuildRunner 不再调用 time_ns

```python
@pytest.mark.asyncio
async def test_docker_build_uses_valid_unique_name(monkeypatch, app_dir):
    fake = FakeDockerClient(exit_code=0)
    monkeypatch.setattr(docker, "from_env", lambda: fake)

    result = await BuildRunner(mode="docker").run(app_dir)

    assert result.ok
    assert fake.created_name.startswith("paperforge-build-")
```

### 52.4 Generator 路径穿越

```python
def test_manifest_rejects_path_traversal():
    with pytest.raises(ValidationError):
        AppManifest.model_validate({
            "app_id": "app_1",
            "files": [{
                "path": "../../api/main.py",
                "content": "owned",
            }],
        })
```

### 52.5 SSE 后端重启恢复

```python
@pytest.mark.asyncio
async def test_event_replay_after_manager_restart(storage):
    manager = EventManager(storage)
    await manager.publish(Event(run_id="run_1", type="message.delta", data={"delta": "A"}))
    await manager.publish(Event(run_id="run_1", type="message.delta", data={"delta": "B"}))

    restarted = EventManager(storage)
    rows = storage.list_run_events("run_1", after_seq=0)

    assert [row["seq"] for row in rows] == [1, 2]
    event = await restarted.publish(Event(run_id="run_1", type="run.finished", data={}))
    assert event.seq == 3
```

### 52.6 sandbox 未 ready 不可返回成功

```python
@pytest.mark.asyncio
async def test_sandbox_health_timeout_is_failure(monkeypatch, ctx):
    monkeypatch.setattr(DockerSandboxManager, "start", AsyncMock(return_value={
        "id": "sb_1",
        "status": "running",
    }))
    monkeypatch.setattr(DockerSandboxManager, "wait_for_ready", AsyncMock(return_value=False))

    result = await handle_run_sandbox({"app_path": "/app"}, ctx)

    assert result.status == ToolStatus.FAILED
    assert result.code == "PREVIEW_NOT_READY"
```

## 53. 必须新增的前端测试

### 53.1 Ctrl+Enter 只发送一次

```tsx
it("submits once on Ctrl+Enter", async () => {
  const user = userEvent.setup();
  vi.mocked(api.sendMessage).mockResolvedValue({ status: "queued", run_id: "r1" });

  render(<Composer />);
  const input = screen.getByRole("textbox");
  await user.type(input, "build app");
  await user.keyboard("{Control>}{Enter}{/Control}");

  expect(api.sendMessage).toHaveBeenCalledTimes(1);
});
```

### 53.2 hydration 后从 cursor 连接

```tsx
it("connects SSE from snapshot cursor", async () => {
  vi.mocked(api.getRunState).mockResolvedValue({
    run,
    messages: [],
    artifacts: [],
    sandbox: null,
    pending_approvals: [],
    event_cursor: 42,
  });

  renderHook(() => useRunSession("run_1"));

  await waitFor(() => {
    expect(mockSse.connect).toHaveBeenCalledWith("run_1", 42);
  });
});
```

### 53.3 status 更新不重连 SSE

```tsx
it("does not reconnect when run status changes", async () => {
  const { rerender } = renderHook(() => useRunSession("run_1"));
  act(() => useAppStore.getState().updateCurrentRun({ status: "running" }));
  rerender();
  expect(mockSse.connect).toHaveBeenCalledTimes(1);
});
```

### 53.4 切换 Run 清理 preview

```tsx
it("clears sandbox and preview on run switch", () => {
  useAppStore.getState().setSandbox({ id: "old", status: "running" });
  useAppStore.getState().setCurrentRun(runB);
  expect(useAppStore.getState().sandbox).toBeNull();
  expect(useAppStore.getState().previewState.status).toBe("idle");
});
```

## 54. 推荐的 PR 拆分顺序

不要一次提交一个超大重构。建议按下面顺序拆成可验证 PR：

### PR-01：真实状态修复

涉及：

- `ToolStatus`；
- blocked/failed/succeeded；
- verify 与 sandbox 返回真实状态；
- finish 真正结束；
- 对应单测。

验收：任何失败都不会显示 `verified` 或 `preview_ready`。

### PR-02：Build 与 Generator 安全

涉及：

- `time_ns` 修复；
- Docker SDK `to_thread`；
- manifest path validator；
- 固定 npm scripts；
- app root ownership；
- 原子 workspace。

验收：路径穿越和非白名单 script/dependency 被拒绝，Docker 构建真实执行。

### PR-03：Durable SSE

涉及：

- DB seq；
- unique index；
- persist-first；
- cursor replay；
- frontend `useRunSession`；
- 单一 event reducer。

验收：刷新、断网重连、后端重启后消息不丢、不重复。

### PR-04：Message 与 Composer

涉及：

- public message ID；
- optimistic rollback；
- PDF 真上传；
- 双发送修复；
- 运行中输入策略。

验收：任何一次用户操作最多创建一条消息，失败不会留下幽灵消息。

### PR-05：Workspace 与 Preview

涉及：

- app artifact file API；
- preview 状态独立；
- code diff/revision；
- HMR gateway；
- file size 与 directory API。

验收：没有 sandbox 也能编辑代码；只有收到 `preview.ready` 才显示完成。

### PR-06：Verifier 与自动修复循环

涉及：

- npm ci/typecheck/lint/build；
- Playwright；
- acceptance criteria；
- diagnose/apply patch/reverify；
- max repair rounds 与 rollback。

验收：生成的产品必须完成至少一条真实交互测试，而不是只通过关键词扫描。

### PR-07：UI 工作台

涉及：

- 三栏 resizable layout；
- Message Parts；
- Workbench 6 tabs；
- task timeline；
- motion/tokens；
- responsive layout。

验收：真实状态与 UI 一一对应，不再出现“卡片写 complete 但功能未运行”。

## 55. 第二轮复审后的最终判断

PaperForge 现在的主要瓶颈不是模型不够强，也不是 Tailwind 样式不够精致，而是下面五件事尚未成立：

1. **论文事实真正进入产品规划**：当前单论文 card 内容仍丢失。
2. **状态只由真实结果驱动**：blocked、failed、not-ready 仍会被包装成成功。
3. **生成代码经过真实工程闭环**：Docker build 当前还有确定性错误，Verifier 也没有 type/lint/browser 验证。
4. **实时事件可恢复**：当前 persistence 与 replay 没有接起来，前端还存在重连和覆盖竞态。
5. **工作台围绕同一 workspace revision 协作**：聊天、文件、preview、verification 仍是松散状态。

UI 可以参考 ChatGPT、Codex 和 Claude 的交互密度，但必须建立在上述闭环之上。否则即使换成更漂亮的 sidebar、圆角和动效，用户仍然会遇到：状态不可信、消息要刷新、preview 不工作、修改无法继续、生成代码跑不起来。

这一轮建议优先完成 PR-01 到 PR-04。完成后，产品会从“展示型原型”进入“基本可信的 coding workspace”；再做 PR-05 到 PR-07，UI 的高级感和交互流畅度才有稳定基础。
