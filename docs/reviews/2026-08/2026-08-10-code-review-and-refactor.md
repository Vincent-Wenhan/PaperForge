# PaperForge 深度代码审查与系统重构方案

> 审查日期：2026-08-10  
> 审查对象：`Vincent-Wenhan/PaperForge` 当前 `main` 分支、现有 `docs/`、当前前端截图  
> 项目定位：论文 PDF → 多 Agent 理解/规划 → 生成 Next.js 应用 → 验证 → Docker Live Preview  
> 文档性质：**面向下一轮真实重构的工程方案**，不是单纯 UI 改版建议。  
> 代码说明：下文核心代码以“接近可直接迁移”为目标；具体函数签名、字段名应按落地 PR 再与仓库现有 helper 对齐。

---

## 目录

1. Executive Summary  
2. 重新审查后的核心结论  
3. 当前已经做对的部分  
4. 问题优先级总表  
5. 目标架构  
6. P0：真正修好流式输出链路  
7. P0：统一 Provider Streaming，修复 Anthropic Tool Call  
8. P0：修复 PRD → Acceptance Test 契约漂移  
9. P0/P1：重构代码生成器，突破 3 文件瓶颈  
10. P1：Run / Task / Workspace 模型重构  
11. P1：从全局 Phase Gate 改成 Resource Gate  
12. P1：Queue / Interrupt / Follow-up  
13. P1：Agent 过程实时可见  
14. P1：SSE Forward-Compatible Event Envelope  
15. P1：Conversation / Turn 状态模型  
16. P1：前端 UI/UX 全面重构  
17. P1：Workbench 重构  
18. P1：Preview Proxy / Iframe / Logs  
19. P1：Verification Pipeline V2  
20. P1/P2：Paper Parsing 与 Capability Contract  
21. P2：Storage / Event Broker / Worker Recovery  
22. P2：Type Safety 与 API Contract  
23. 测试体系  
24. 可观测性与性能指标  
25. 文档体系重构  
26. 推荐 PR 顺序  
27. 文件级修改清单  
28. 最终验收标准  
29. 参考项目  
30. 审查依据  

---

# 1. Executive Summary

PaperForge 当前已经不是“基础功能没写完”的早期 demo。仓库里已经有 FastAPI、Next.js、SQLite durable storage、`run_events`、per-run `seq`、`/state` snapshot hydration、SSE replay、`message.started/delta/completed/failed`、Task、Approval、Artifact、Workspace revision、Docker sandbox、Preview、Monaco、Changes/Tests/Logs 等基础设施。

因此下一轮**不建议继续横向堆功能，也不建议只做 CSS 美化**。应该把已有能力收敛成三个稳定层次：

```text
1. Realtime Runtime
   Provider Stream
   → Message Stream
   → Durable Event
   → SSE
   → Client Reducer
   → Smooth Render

2. Agent / Workspace Runtime
   Persistent Thread
   → Task
   → Observable Steps
   → Workspace Edits
   → Verification
   → Preview

3. Product UX
   Conversation = command plane
   Workbench    = work surface
   Agent Steps  = observable progress
```

这次重新审查后，最值得优先解决的是四个根问题。

### 根问题 A：流式链路存在，但 hot path 过重

当前每个 LLM text chunk 会进入：

```text
provider chunk
→ UPDATE messages
→ INSERT run_events + 分配 seq
→ push subscriber queue
→ SSE
→ Zustand
→ ReactMarkdown
→ smooth scroll
```

因此“代码里支持 streaming”并不等于“用户看到 ChatGPT 级别的 streaming”。

### 根问题 B：生成器被 3 个文件硬编码限制

当前 `NextjsGenerator` 明确只允许生成：

```text
app/page.tsx
lib/mock-api.ts
lib/real-api.ts
```

这直接限制多页面、组件化、hooks、types、API routes、复杂交互和后续 feature-level 编辑。最终很容易变成“一个巨大的 `page.tsx` + mock + TODO real adapter”。

### 根问题 C：RunPhase 是一次性流水线模型，不适合连续 Agent 会话

当前整体思路是：

```text
INIT → PARSED → COMPOSED → PLANNED
→ GENERATED → VERIFIED → PREVIEW_READY → DONE
```

这对“一次性 pipeline”合理，但用户在产品生成后说“把导航改窄一点”“加一个 history panel”“这个按钮坏了，修一下”时，应该直接操作已有 workspace，而不是重新回到 `INIT`。

### 根问题 D：PRD schema 与 planner prompt 已出现 contract drift

Schema 已经有结构化 top-level `acceptance_criteria`，但 Planner prompt 示例仍主要输出 feature 内的字符串条件，并且 Feature 没稳定 `id`。Verifier 又依赖 top-level executable criteria 判断产品验收。结果可能出现：

```text
PRD 校验通过
→ executable criteria 实际为空
→ Browser acceptance 没有真正覆盖 Must-have
```

这属于产品 correctness 问题，优先级高于视觉优化。

---

# 2. 重新审查后的核心结论

## 2.1 不建议重写技术栈

当前：

```text
FastAPI + Next.js + SSE + SQLite + Docker
```

对 PaperForge 当前阶段完全够用。暂时不需要为了“高级感”引入 Kafka、Temporal、微服务、全量 WebSocket、LangGraph 或其他重型基础设施。

## 2.2 应该重写的是边界

重点重构：

```text
LLM Provider
↓
Normalized Provider Stream

Agent Runtime
↓
Task / Step / Tool

Persistence
↓
MessageStore / EventStore / WorkspaceRevision

Realtime
↓
RunEvent

Frontend
↓
RunEventReducer

Presentation
↓
Turn / Steps / Workbench
```

## 2.3 目标产品形态

PaperForge 更适合成为：

> **面向论文产品化的 Agent Workspace**

而不是：

```text
论文上传器 + Chatbot + 永久打开的 Preview iframe
```

用户看到的核心应该是：

```text
Conversation
  ├─ 用户目标
  ├─ Agent 当前正在做什么
  ├─ 这一轮改了什么
  └─ 最终回复

Workbench
  ├─ Preview
  ├─ Code
  ├─ Changes
  ├─ Tests
  ├─ Artifacts
  └─ Logs
```

---

# 3. 当前已经做对的部分

以下部分不应该再次推倒重来。

## 3.1 Durable Run Events

当前已有：

```sql
run_events (
    id,
    run_id,
    task_id,
    seq,
    type,
    data,
    created_at
)
```

并有 `(run_id, seq)` 唯一约束。这个方向正确。

## 3.2 Message Lifecycle

已有：

```text
message.started
message.delta
message.completed
message.failed
```

而且 streaming message 先创建 durable row，再发 lifecycle event。这也是正确方向。

## 3.3 Snapshot + Cursor Hydration

当前前端已经是：

```text
GET /state
↓
hydrate snapshot
↓
event_cursor
↓
SSE after_seq
```

因此后续要优化的是 transport、render 和 write amplification，而不是重新设计 cursor。

## 3.4 Artifact / Approval / Task / Workspace Revision

这些 domain 已经存在。下一步应明确它们与 Task/Turn 的归属关系和 UI presentation，而不是新增重复状态。

---

# 4. 问题优先级总表

| 优先级 | 问题 | 影响 | 建议 |
|---|---|---|---|
| P0 | 每个 text chunk 写 message | Streaming 卡顿 | 40ms micro-batch + 250ms checkpoint |
| P0 | 每个 delta 再 durable INSERT event | DB write amplification | 合并 delta 后 durable |
| P0 | Anthropic stream 丢 tool call | Agent correctness | Provider stream normalization |
| P0 | PRD executable acceptance 漂移 | 验证可能名义通过 | PRD V2 + validator |
| P0 | Generator 只能生成 3 文件 | 产品质量上限低 | WorkspacePlan + safe patch tools |
| P1 | DONE 后 follow-up reset INIT | 连续编辑体验差 | Run/Task/Resource 分离 |
| P1 | 全局 phase gate | 工具难以自然迭代 | Resource prerequisite gate |
| P1 | Composer 运行中完全 disabled | 不像现代 Agent | Queue / Interrupt |
| P1 | named SSE types hardcode | 新 event 兼容性差 | 单一 envelope |
| P1 | unknown event 触发 hydrate | 协议脆弱 | unknown=ignored |
| P1 | delta 触发 Zustand+Markdown+scroll | 前端抖动 | rAF + memo + smart scroll |
| P1 | AgentActivity 与消息脱节 | 过程不可理解 | inline Steps |
| P1 | Workbench 永久 58% | 空白、生硬 | adaptive workbench |
| P1 | `PreviewPanel.tsx` 约 900 行 | 维护困难 | 模块化 |
| P1 | Logs polling | 非实时 | log delta event |
| P1 | Preview proxy buffer | 资源/HMR 不理想 | shared client + streaming |
| P1 | Repair 同样只允许 3 文件 | 复杂 app 修不了 | SafeWorkspacePolicy |
| P1 | Verifier 关键词 coverage | false positive | executable tests |
| P2 | Event subscriber 仅内存 | 多 worker 不可靠 | EventBroker abstraction |
| P2 | TaskManager 仅内存 | restart 后悬空 | durable claim/lease |
| P2 | Store 大一统 + `any` | 状态易漂移 | slices + generated types |
| P2 | Docs historical review 混 architecture | 容易重复实现 | docs 分层 |

---

# 5. 目标架构

```text
┌─────────────────────────────────────────────────────────┐
│                     User / Browser                      │
└───────────────────────────┬─────────────────────────────┘
                            ▼
                 ┌──────────────────────┐
                 │ Conversation / Task  │
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │    Orchestrator      │
                 │ Goal → Plan → Act    │
                 └──────┬────────┬──────┘
                        │        │
                      LLM      Tools
                        ▼        ▼
              ┌─────────────┐ ┌─────────────────┐
              │ProviderEvent│ │Workspace/Sandbox│
              └──────┬──────┘ └────────┬────────┘
                     └─────────┬────────┘
                               ▼
                    ┌───────────────────┐
                    │ Observable Steps  │
                    └─────────┬─────────┘
                              ▼
                    ┌───────────────────┐
                    │    EventStore     │
                    │ durable seq/replay│
                    └─────────┬─────────┘
                              ▼
                         EventBroker
                              ▼
                             SSE
                              ▼
                    ┌───────────────────┐
                    │ RunEventReducer   │
                    └─────────┬─────────┘
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         Conversation      Workbench        Status
         Turn/Steps    Preview/Code/Diff    Sidebar
```

三类状态必须分离：

```text
Server Source of Truth:
runs/messages/tasks/events/artifacts/approvals/revisions/sandboxes

Derived Realtime:
streaming message/active task/active steps/preview

Pure UI:
sidebar/workbench mode/active tab/draft/scroll lock
```

---

# 6. P0：真正修好流式输出链路

## 6.1 当前 hot path

当前 `_stream_llm()` 的关键路径实际上是：

```python
async for chunk in stream_fn(...):
    if chunk.content:
        content_parts.append(chunk.content)
        self.storage.append_message_delta(
            message_id,
            chunk.content,
        )
        await emit.message_delta(
            message_id,
            chunk.content,
        )
```

`append_message_delta()` 会同步 SQLite UPDATE；`emit.message_delta()` 又会 durable append 到 `run_events`。因此一个很小的 provider delta 会产生两次持久化动作。

建议：

```text
Provider raw delta
     ▼
Server Stream Buffer
  40ms / min chars
     ▼
Durable message.delta
     ├──── SSE
     └──── message checkpoint 250ms
```

## 6.2 新增 `StreamWriter`

新文件：

```text
paperforge/orchestrator/stream_writer.py
```

```python
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StreamWriter:
    run_id: str
    message_id: str
    storage: Any
    emit: Any

    flush_interval_s: float = 0.040
    checkpoint_interval_s: float = 0.250
    min_flush_chars: int = 24

    _pending: list[str] = field(default_factory=list)
    _full: list[str] = field(default_factory=list)
    _pending_chars: int = 0

    _last_flush_at: float = field(default_factory=time.monotonic)
    _last_checkpoint_at: float = field(default_factory=time.monotonic)

    async def push_text(self, text: str) -> None:
        if not text:
            return

        self._pending.append(text)
        self._full.append(text)
        self._pending_chars += len(text)

        now = time.monotonic()

        if (
            self._pending_chars >= self.min_flush_chars
            or now - self._last_flush_at >= self.flush_interval_s
        ):
            await self.flush_delta()

        if (
            now - self._last_checkpoint_at
            >= self.checkpoint_interval_s
        ):
            await self.checkpoint()

    async def flush_delta(self) -> None:
        if not self._pending:
            return

        delta = "".join(self._pending)
        self._pending.clear()
        self._pending_chars = 0
        self._last_flush_at = time.monotonic()

        await self.emit.message_delta(
            self.message_id,
            delta,
        )

    async def checkpoint(self) -> None:
        content = "".join(self._full)

        await asyncio.to_thread(
            self.storage.update_streaming_message_content,
            self.message_id,
            content,
        )

        self._last_checkpoint_at = time.monotonic()

    async def finish(
        self,
        tool_calls: list[Any] | None = None,
    ) -> str:
        await self.flush_delta()

        content = "".join(self._full)

        await asyncio.to_thread(
            self.storage.complete_message,
            self.message_id,
            content,
            [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "args": tc.args,
                }
                for tc in (tool_calls or [])
            ] or None,
        )

        await self.emit.message_completed(
            self.message_id,
            content,
        )

        return content
```

## 6.3 Storage checkpoint

```python
def update_streaming_message_content(
    self,
    public_id: str,
    content: str,
) -> None:
    with self._lock, self._conn() as conn:
        conn.execute(
            """
            UPDATE messages
            SET content = ?
            WHERE public_id = ?
              AND status = 'streaming'
            """,
            (content, public_id),
        )
```

不要再对每个 tiny delta 做：

```sql
content = content || delta
```

## 6.4 `_stream_llm()` 集成

```python
async def _stream_llm(
    self,
    model: str,
    messages: list[Message],
    tools: list[Any],
    emit: EventEmitter,
    run_id: str,
) -> ChatResponse:
    stream_fn = getattr(self.llm, "stream", None)

    if stream_fn is None:
        return await self.llm.chat(
            model=model,
            messages=messages,
            tools=tools,
        )

    message_id = f"msg_{uuid.uuid4().hex}"
    tool_calls: list[ToolCall] = []
    finish_reason: str | None = None

    self.storage.create_streaming_message(
        run_id,
        message_id,
    )
    await emit.message_started(message_id)

    writer = StreamWriter(
        run_id=run_id,
        message_id=message_id,
        storage=self.storage,
        emit=emit,
    )

    try:
        async for chunk in stream_fn(
            model=model,
            messages=messages,
            tools=tools,
        ):
            if chunk.content:
                await writer.push_text(
                    chunk.content
                )

            if chunk.tool_calls:
                tool_calls.extend(
                    chunk.tool_calls
                )

            if chunk.finish_reason:
                finish_reason = (
                    chunk.finish_reason
                )

    except asyncio.CancelledError:
        self.storage.fail_message(
            message_id,
            "Message stream cancelled",
        )
        with contextlib.suppress(Exception):
            await emit.message_failed(
                message_id,
                "Message stream cancelled",
            )
        raise

    except Exception as exc:
        self.storage.fail_message(
            message_id,
            str(exc),
        )
        await emit.message_failed(
            message_id,
            str(exc),
        )
        raise

    final_content = await writer.finish(
        tool_calls
    )

    return ChatResponse(
        content=final_content or None,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        message_id=message_id,
    )
```

## 6.5 前端 `requestAnimationFrame` batching

新文件：

```text
web/lib/realtime/stream-buffer.ts
```

```typescript
import { useAppStore } from "@/lib/store";

const pending =
  new Map<string, string>();

let frameId: number | null = null;

export function enqueueMessageDelta(
  messageId: string,
  delta: string,
) {
  if (!delta) return;

  pending.set(
    messageId,
    (pending.get(messageId) ?? "")
      + delta,
  );

  if (frameId !== null) return;

  frameId = requestAnimationFrame(() => {
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
  });
}

export function flushMessageDeltas() {
  if (frameId !== null) {
    cancelAnimationFrame(frameId);
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
case "message.delta":
  if (data.message_id) {
    enqueueMessageDelta(
      data.message_id,
      data.delta ?? data.text ?? "",
    );
  }
  return "applied";

case "message.completed":
  flushMessageDeltas();

  if (data.message_id) {
    store.completeMessage(
      data.message_id,
      data.content ?? "",
    );
  }

  return "applied";
```



# 7. P0：统一 Provider Streaming，修复 Anthropic Tool Call

## 7.1 当前问题

当前 Anthropic provider 的 `chat()` 会解析 `tool_use`，但 `stream()` 只消费 `stream.text_stream`，因此带工具的流式调用可能只拿到文本而丢失 tool call。Agent 系统里这不是单纯“流不流”的问题，而是 correctness 问题。

## 7.2 最低风险 Hotfix

在完整 native tool stream adapter 完成前，可以先保证 correctness：

```python
async def stream(
    self,
    model: str,
    messages: list[Message],
    tools: list[ToolDefinition] | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> AsyncIterator[Chunk]:

    # 临时策略：有 tools 时先保证 tool call 不丢。
    if tools:
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
                tool_calls=response.tool_calls
            )

        yield Chunk(
            finish_reason=(
                response.finish_reason
            )
        )
        return

    system, msgs = self._split_messages(
        messages
    )

    kwargs = {
        "model": (
            model or self.default_model
        ),
        "system": system,
        "messages": msgs,
        "temperature": temperature,
        "max_tokens": max_tokens or 4096,
    }

    async with self.client.messages.stream(
        **kwargs
    ) as stream:
        async for text in stream.text_stream:
            yield Chunk(content=text)

    yield Chunk(finish_reason="stop")
```

这个版本暂时牺牲 Anthropic tool turn 的 token streaming，但不会牺牲 tool call 正确性。

## 7.3 正式方案：Provider-neutral event

```python
from dataclasses import dataclass
from typing import Any, Literal


ProviderEventKind = Literal[
    "text_delta",
    "tool_start",
    "tool_args_delta",
    "tool_done",
    "usage",
    "done",
]


@dataclass(slots=True)
class ProviderStreamEvent:
    kind: ProviderEventKind

    text: str | None = None

    tool_call_id: str | None = None
    tool_name: str | None = None

    arguments_delta: str | None = None
    arguments: dict[str, Any] | None = None

    finish_reason: str | None = None

    input_tokens: int | None = None
    output_tokens: int | None = None
```

统一 interface：

```python
class LLMClient(ABC):

    @abstractmethod
    async def stream_events(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> AsyncIterator[ProviderStreamEvent]:
        ...
```

Orchestrator 只看统一事件：

```python
tool_buffers: dict[
    str,
    dict[str, Any],
] = {}

async for event in self.llm.stream_events(
    model=model,
    messages=messages,
    tools=tools,
):
    if event.kind == "text_delta":
        await writer.push_text(
            event.text or ""
        )

    elif event.kind == "tool_start":
        tool_buffers[
            event.tool_call_id
        ] = {
            "name": event.tool_name,
            "args_text": "",
        }

    elif event.kind == "tool_args_delta":
        tool_buffers[
            event.tool_call_id
        ]["args_text"] += (
            event.arguments_delta or ""
        )

    elif event.kind == "tool_done":
        buffer = tool_buffers[
            event.tool_call_id
        ]

        args = (
            event.arguments
            if event.arguments is not None
            else json.loads(
                buffer["args_text"]
                or "{}"
            )
        )

        tool_calls.append(
            ToolCall(
                id=event.tool_call_id,
                name=(
                    event.tool_name
                    or buffer["name"]
                ),
                args=args,
            )
        )

    elif event.kind == "done":
        finish_reason = (
            event.finish_reason
        )
```

这样以后 OpenAI / Anthropic / 其他兼容 provider 的差异只存在 adapter 层。

---

# 8. P0：修复 PRD → Acceptance Test 契约漂移

## 8.1 当前问题

当前 schema 有：

```python
class AcceptanceCriterion(BaseModel):
    id: str
    feature_id: str
    priority: Literal[
        "must", "should", "could"
    ]
    description: str
    test_kind: Literal[
        "route",
        "text",
        "interaction",
        "visual",
        "api",
    ]
    selector: str | None = None
    expected: ...
```

但当前 `Feature` 没有稳定 `id`：

```python
class Feature(BaseModel):
    name: str
    description: str = ""
    acceptance_criteria: list[str]
```

同时 Planner prompt 的示例主要要求 feature 内的字符串 `acceptance_criteria`，没有要求 top-level executable criteria。由于 schema 里的 top-level list 有默认空值，Planner 即使不输出也可能通过 validation。

## 8.2 PRD V2

```python
from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    Field,
    model_validator,
)


Priority = Literal[
    "must",
    "should",
    "could",
]


class Feature(BaseModel):
    id: str
    name: str
    description: str = ""
    priority: Priority
    user_value: str = ""

    acceptance_notes: list[str] = Field(
        default_factory=list
    )


class AcceptanceCriterion(BaseModel):
    id: str
    feature_id: str
    priority: Priority

    description: str

    test_kind: Literal[
        "route",
        "text",
        "interaction",
        "api",
        "visual",
    ]

    route: str = "/"
    selector: str | None = None

    action: Literal[
        "none",
        "click",
        "fill",
        "upload",
        "select",
    ] = "none"

    input_value: str | None = None

    expected: (
        str | bool | int | float | None
    ) = None


class PRD(BaseModel):
    prd_id: str

    product_name: str
    one_liner: str = ""

    target_users: list[str] = Field(
        default_factory=list
    )

    features: list[Feature] = Field(
        default_factory=list
    )

    acceptance_criteria: list[
        AcceptanceCriterion
    ] = Field(default_factory=list)

    mock_strategy: str = ""
    data_strategy: str = ""

    key_screens: list[str] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_executable_acceptance(
        self,
    ) -> "PRD":
        feature_ids = {
            feature.id
            for feature in self.features
        }

        criteria_by_feature: dict[
            str,
            list[AcceptanceCriterion],
        ] = {}

        for criterion in (
            self.acceptance_criteria
        ):
            if (
                criterion.feature_id
                not in feature_ids
            ):
                raise ValueError(
                    "Acceptance criterion "
                    f"{criterion.id!r} "
                    "references unknown feature "
                    f"{criterion.feature_id!r}"
                )

            criteria_by_feature.setdefault(
                criterion.feature_id,
                [],
            ).append(criterion)

        missing_must = [
            feature.id
            for feature in self.features
            if (
                feature.priority == "must"
                and not criteria_by_feature.get(
                    feature.id
                )
            )
        ]

        if missing_must:
            raise ValueError(
                "Every must-have feature "
                "needs at least one executable "
                "acceptance criterion: "
                + ", ".join(missing_must)
            )

        return self
```

## 8.3 Planner prompt 必须同步

建议输出：

```json
{
  "prd": {
    "prd_id": "prd_001",
    "product_name": "Paper Explorer",
    "features": [
      {
        "id": "feature_upload",
        "name": "PDF upload",
        "description": "Upload a paper",
        "priority": "must",
        "acceptance_notes": [
          "PDF can be selected",
          "selected filename is visible"
        ]
      }
    ],
    "acceptance_criteria": [
      {
        "id": "ac_upload_1",
        "feature_id": "feature_upload",
        "priority": "must",
        "description": "Upload control is visible",
        "test_kind": "interaction",
        "route": "/",
        "selector": "[data-testid='paper-upload']",
        "action": "none",
        "expected": true
      }
    ]
  }
}
```

## 8.4 Generator 强制 stable selector

Prompt 增加：

```text
Every interactive element referenced by a PRD acceptance criterion
MUST expose the exact data-testid required by that criterion.

Do not replace the selector with a CSS class or text-only locator.
```

生成：

```tsx
<input
  data-testid="paper-upload"
  type="file"
  accept="application/pdf"
/>
```

## 8.5 Browser Acceptance Runner

```python
async def execute_acceptance_criterion(
    page,
    base_url: str,
    criterion: AcceptanceCriterion,
) -> dict:
    await page.goto(
        f"{base_url}{criterion.route}"
    )

    locator = (
        page.locator(
            criterion.selector
        )
        if criterion.selector
        else None
    )

    if criterion.action == "click":
        assert locator is not None
        await locator.click()

    elif criterion.action == "fill":
        assert locator is not None
        await locator.fill(
            criterion.input_value or ""
        )

    if criterion.expected is True:
        assert locator is not None
        passed = await locator.is_visible()

    elif isinstance(
        criterion.expected,
        str,
    ):
        passed = (
            criterion.expected
            in await page.content()
        )

    else:
        passed = True

    return {
        "criterion_id": criterion.id,
        "feature_id": criterion.feature_id,
        "passed": passed,
    }
```

---

# 9. P0/P1：重构代码生成器，突破 3 文件瓶颈

## 9.1 不应该取消安全边界

错误方向：

```text
LLM 可以自由写任何路径
```

正确方向：

```text
精确 3 文件白名单
→ 升级为 Workspace Policy

允许有限 root
拒绝 absolute path
拒绝 ..
拒绝 node_modules/.git
限制单文件大小
限制总 patch 大小
限制 dependencies
保护配置文件
每批修改创建 revision
```

## 9.2 `SafeWorkspacePolicy`

```python
from pathlib import PurePosixPath


class SafeWorkspacePolicy:
    ALLOWED_ROOTS = {
        "app",
        "components",
        "hooks",
        "lib",
        "types",
        "public",
    }

    BLOCKED_PREFIXES = {
        ".git",
        "node_modules",
        ".next",
    }

    PROTECTED_FILES = {
        "package-lock.json",
        "next.config.mjs",
        "tsconfig.json",
    }

    MAX_FILE_BYTES = 400_000
    MAX_PATCH_BYTES = 1_500_000

    def normalize(
        self,
        raw_path: str,
    ) -> str:
        value = (
            raw_path
            .replace("\\", "/")
            .lstrip("/")
        )

        path = PurePosixPath(value)

        if ".." in path.parts:
            raise ValueError(
                "Path traversal is not allowed"
            )

        if not path.parts:
            raise ValueError("Empty path")

        root = path.parts[0]

        if root not in self.ALLOWED_ROOTS:
            raise ValueError(
                f"Root {root!r} is not writable"
            )

        if any(
            value == prefix
            or value.startswith(
                prefix + "/"
            )
            for prefix
            in self.BLOCKED_PREFIXES
        ):
            raise ValueError(
                "Protected workspace path"
            )

        return str(path)

    def validate_content(
        self,
        content: str,
    ) -> None:
        size = len(
            content.encode("utf-8")
        )

        if size > self.MAX_FILE_BYTES:
            raise ValueError(
                "Generated file is too large"
            )
```

## 9.3 WorkspacePlan

```python
from pydantic import BaseModel, Field
from typing import Literal


class RouteSpec(BaseModel):
    path: str
    purpose: str


class ComponentSpec(BaseModel):
    path: str
    purpose: str
    reusable: bool = True


class FileSpec(BaseModel):
    path: str

    kind: Literal[
        "route",
        "component",
        "hook",
        "adapter",
        "type",
        "fixture",
        "api",
    ]

    purpose: str

    depends_on: list[str] = Field(
        default_factory=list
    )


class WorkspacePlan(BaseModel):
    app_name: str

    routes: list[RouteSpec]
    components: list[ComponentSpec]
    files: list[FileSpec]

    dependencies: dict[
        str,
        str,
    ] = Field(default_factory=dict)

    acceptance_test_ids: list[str] = (
        Field(default_factory=list)
    )
```

## 9.4 Patch schema

```python
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

## 9.5 Safe apply

```python
def apply_workspace_patch(
    workspace_root: Path,
    patch: WorkspacePatch,
    policy: SafeWorkspacePolicy,
) -> list[str]:

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

    changed: list[str] = []

    for item in patch.files:
        relative = policy.normalize(
            item.path
        )

        target = (
            workspace_root / relative
        ).resolve()

        target.relative_to(
            workspace_root.resolve()
        )

        if (
            relative
            in policy.PROTECTED_FILES
        ):
            raise ValueError(
                f"Protected file: {relative}"
            )

        if item.operation == "delete":
            if target.exists():
                target.unlink()

        else:
            content = item.content or ""

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

## 9.6 Generation V2

```text
PRD
 ↓
WorkspacePlanner
 ↓
WorkspacePlan
 ↓
Template Scaffold
 ↓
Generate logical file batches
 ↓
Safe patches + revisions
 ↓
Typecheck
 ↓
Repair
 ↓
Build
 ↓
Preview
 ↓
Browser acceptance
```

核心：

```python
async def generate_workspace(
    prd: PRD,
    plan: WorkspacePlan,
    workspace: Workspace,
    llm: LLMClient,
    progress: ProgressReporter,
) -> None:

    groups = group_file_specs(
        plan.files
    )

    for group_name, specs in groups:
        step_id = await progress.start(
            kind="codegen",
            title=(
                f"Generating {group_name}"
            ),
        )

        dependencies = {
            dep
            for spec in specs
            for dep in spec.depends_on
        }

        context = (
            workspace.read_context(
                files=list(
                    dependencies
                )
            )
        )

        patch = await generate_file_batch(
            prd=prd,
            specs=specs,
            context=context,
            llm=llm,
        )

        changed = (
            workspace.apply_patch(
                patch
            )
        )

        revision = workspace.snapshot(
            source=(
                f"generate:{group_name}"
            ),
            changed_files=changed,
        )

        await progress.complete(
            step_id,
            summary=(
                f"{len(changed)} files changed"
            ),
            metadata={
                "revision_id": revision.id,
            },
        )
```

## 9.7 给 Agent 真正的 Workspace Tools

至少新增：

```text
inspect_workspace
read_workspace_file
apply_workspace_patch
run_checks
start_preview
```

例如：

```python
ToolDefinition(
    name="apply_workspace_patch",
    description=(
        "Apply a bounded safe patch "
        "to the current generated app."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string"
            },
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string"
                        },
                        "operation": {
                            "enum": [
                                "create",
                                "replace",
                                "delete",
                            ]
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
)
```

这样用户生成完成后再说：

```text
“把首页改成双栏，右边加历史记录”
```

Agent 可以直接：

```text
inspect
→ read
→ patch
→ typecheck
→ preview
```

而不是重新 productize。

---

# 10. P1：Run / Task / Workspace 模型重构

## 10.1 Run / Thread

```python
class Run:
    id: str
    title: str

    workspace_id: str | None

    created_at: datetime
    updated_at: datetime
```

Run 是持久会话，不应该等同于一次 task。

## 10.2 Task

```python
class Task:
    id: str
    run_id: str
    user_message_id: str

    goal: str

    status: Literal[
        "queued",
        "running",
        "waiting_approval",
        "completed",
        "failed",
        "cancelled",
    ]

    display_phase: str | None

    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
```

## 10.3 Step

```python
class Step:
    id: str
    task_id: str

    kind: Literal[
        "paper_parse",
        "planning",
        "tool",
        "codegen",
        "edit",
        "build",
        "test",
        "preview",
    ]

    title: str

    status: Literal[
        "pending",
        "running",
        "completed",
        "failed",
    ]

    detail: str | None
    summary: str | None
```

## 10.4 WorkspaceState

```python
from dataclasses import (
    dataclass,
    field,
)


@dataclass
class WorkspaceState:
    paper_ids: list[str] = field(
        default_factory=list
    )

    capability_card_ids: list[str] = (
        field(default_factory=list)
    )

    composition_id: str | None = None
    prd_id: str | None = None

    app_id: str | None = None
    workspace_path: str | None = None
    revision_id: str | None = None

    verification_report_id: (
        str | None
    ) = None

    sandbox_id: str | None = None
    preview_url: str | None = None
```



# 11. P1：从全局 Phase Gate 改成 Resource Gate

## 11.1 为什么需要改

当前工具是否允许调用主要依赖：

```python
if call.name not in ALLOWED_TOOLS.get(
    self.phase,
    set(),
):
    ...
```

这个模型把两件不同的事情混在一起：

```text
A. 当前 Task 正在显示哪个阶段
B. 当前真实资源是否已经存在
```

例如产品已经有 workspace 时，用户只是想修一个 UI bug，工具是否可用应该取决于“workspace 是否存在”，而不是整个 Run 的 phase 是否刚好是某个值。

## 11.2 ToolSpec

```python
from dataclasses import (
    dataclass,
    field,
)
from typing import Literal


ToolRisk = Literal[
    "read",
    "workspace_write",
    "sandbox_exec",
    "network",
    "destructive",
]


@dataclass(frozen=True)
class ToolSpec:
    name: str

    requires: frozenset[str] = field(
        default_factory=frozenset
    )

    produces: frozenset[str] = field(
        default_factory=frozenset
    )

    risk: ToolRisk = "read"
```

注册：

```python
TOOL_SPECS = {
    "parse_paper": ToolSpec(
        name="parse_paper",
        requires=frozenset({
            "paper"
        }),
        produces=frozenset({
            "capability_card"
        }),
        risk="read",
    ),

    "plan_product": ToolSpec(
        name="plan_product",
        requires=frozenset({
            "capability_card"
        }),
        produces=frozenset({
            "prd"
        }),
        risk="read",
    ),

    "generate_nextjs_app": ToolSpec(
        name="generate_nextjs_app",
        requires=frozenset({
            "prd"
        }),
        produces=frozenset({
            "workspace"
        }),
        risk="workspace_write",
    ),

    "apply_workspace_patch": ToolSpec(
        name="apply_workspace_patch",
        requires=frozenset({
            "workspace"
        }),
        produces=frozenset({
            "workspace_modified"
        }),
        risk="workspace_write",
    ),

    "run_checks": ToolSpec(
        name="run_checks",
        requires=frozenset({
            "workspace"
        }),
        risk="sandbox_exec",
    ),

    "start_preview": ToolSpec(
        name="start_preview",
        requires=frozenset({
            "workspace"
        }),
        produces=frozenset({
            "sandbox"
        }),
        risk="sandbox_exec",
    ),
}
```

## 11.3 Resource gate

```python
def available_resources(
    state: WorkspaceState,
) -> set[str]:
    resources: set[str] = set()

    if state.paper_ids:
        resources.add("paper")

    if state.capability_card_ids:
        resources.add(
            "capability_card"
        )

    if state.prd_id:
        resources.add("prd")

    if state.workspace_path:
        resources.add("workspace")

    if state.sandbox_id:
        resources.add("sandbox")

    return resources


def check_tool_prerequisites(
    tool_name: str,
    state: WorkspaceState,
) -> tuple[bool, list[str]]:
    spec = TOOL_SPECS[
        tool_name
    ]

    missing = sorted(
        spec.requires
        - available_resources(state)
    )

    return (
        len(missing) == 0,
        missing,
    )
```

Orchestrator：

```python
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
        code="resource_prerequisite",
        error=(
            "Missing required resources: "
            + ", ".join(missing)
        ),
        retryable=True,
    ).model_dump_json()
```

`Task.display_phase` 仍可保留给 UI：

```text
understanding
planning
editing
verifying
previewing
```

但不再作为真正的权限门。

---

# 12. P1：Queue / Interrupt / Follow-up

## 12.1 当前交互问题

当前 Agent running 时：

```text
textarea disabled
附件按钮 disabled
再次发送被 409 拒绝
```

这让 PaperForge 更像一个 job runner，而不是 ChatGPT/Codex 风格的持续 Agent。

## 12.2 Message API

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

## 12.3 MVP per-run queue

```python
from collections import defaultdict
import asyncio


class RunQueue:
    def __init__(self) -> None:
        self._queues: dict[
            str,
            asyncio.Queue[str],
        ] = defaultdict(
            asyncio.Queue
        )

        self._workers: dict[
            str,
            asyncio.Task,
        ] = {}

    async def enqueue(
        self,
        run_id: str,
        task_id: str,
    ) -> None:
        await self._queues[
            run_id
        ].put(task_id)

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
                self._worker(run_id)
            )

    async def _worker(
        self,
        run_id: str,
    ) -> None:
        queue = self._queues[
            run_id
        ]

        while not queue.empty():
            task_id = await queue.get()

            try:
                await execute_task(
                    run_id=run_id,
                    task_id=task_id,
                )
            finally:
                queue.task_done()
```

## 12.4 Endpoint

```python
@router.post("/{run_id}/messages")
async def send_message(
    run_id: str,
    req: MessageCreate,
    request: Request,
) -> dict:
    storage = get_storage()

    run = storage.get_run(run_id)

    if not run:
        raise HTTPException(
            404,
            "Run not found",
        )

    running = (
        task_manager.is_running(
            run_id
        )
    )

    if (
        running
        and req.mode == "start"
    ):
        raise HTTPException(
            409,
            "Run is busy; use queue or interrupt",
        )

    if (
        running
        and req.mode == "interrupt"
    ):
        await task_manager.cancel_and_wait(
            run_id
        )

    message = storage.add_message(
        run_id=run_id,
        role="user",
        content=req.content,
        public_id=req.public_id,
    )

    task = storage.create_task(
        run_id=run_id,
        title=req.content[:120],
        goal=req.content,
        status="queued",
        phase="queued",
    )

    await run_queue.enqueue(
        run_id,
        task["id"],
    )

    return {
        "status": "queued",
        "task_id": task["id"],
        "message": message,
    }
```

这里**不要再因为上一轮 `DONE` 就自动把整个 Run phase reset 到 INIT**。Task 是新的，但 workspace/paper/prd 等资源仍然存在。

## 12.5 Composer 不再运行时锁死

```tsx
<textarea
  ref={textareaRef}
  value={input}
  onChange={(event) => {
    setInput(
      event.target.value
    );
  }}
  placeholder={
    isRunning
      ? "Add a follow-up..."
      : "Ask PaperForge..."
  }
  disabled={sending}
/>
```

## 12.6 修 optimistic message ID

当前前端已经创建 optimistic ID，但应该把它传给后端并把用户消息视为 completed：

```typescript
const optimisticId =
  crypto.randomUUID();

addMessage({
  id: optimisticId,
  public_id: optimisticId,
  role: "user",
  content,
  streaming: false,
  status: "completed",
});

const mode =
  isRunning
    ? "queue"
    : "start";

await api.sendMessage(
  currentRun.id,
  content,
  paperIds,
  optimisticId,
  mode,
);
```

## 12.7 运行中按钮

建议：

```text
[ + ]  Add a follow-up...                    [Queue ↑]
```

下拉：

```text
Send after current task
Interrupt current task and send
```

Stop 独立为小图标：

```text
■
```

---

# 13. P1：Agent 过程实时可见

“流式输出”对 PaperForge 应分成两类。

### Text streaming

```text
模型正在说什么
```

### Execution streaming

```text
Agent 正在做什么
```

第二类对于论文→产品长任务更重要。

理想表现：

```text
✓ Read paper
✓ Extracted capability card
✓ Created PRD
● Generating interface
  └─ 8 files changed
○ Running typecheck
○ Starting preview
```

## 13.1 事件 taxonomy

```text
task.queued
task.started
task.completed
task.failed

step.started
step.progress
step.completed
step.failed

file.changed

build.started
build.log.delta
build.completed
build.failed
```

## 13.2 ProgressReporter

```python
class ProgressReporter:
    def __init__(
        self,
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
        metadata: dict | None = None,
    ) -> str:
        step = self.storage.create_step(
            task_id=self.task_id,
            kind=kind,
            title=title,
            status="running",
            metadata=metadata,
        )

        await self.emit.emit(
            "step.started",
            {
                "step_id": step["id"],
                "kind": kind,
                "title": title,
                "metadata": (
                    metadata or {}
                ),
            },
            task_id=self.task_id,
        )

        return step["id"]

    async def progress(
        self,
        step_id: str,
        *,
        percent: float | None = None,
        detail: str | None = None,
    ) -> None:
        await self.emit.emit(
            "step.progress",
            {
                "step_id": step_id,
                "percent": percent,
                "detail": detail,
            },
            task_id=self.task_id,
        )

    async def complete(
        self,
        step_id: str,
        *,
        summary: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.storage.complete_step(
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
            task_id=self.task_id,
        )
```

## 13.3 Parser 进度

```python
step_id = await progress.start(
    kind="paper_parse",
    title="Reading paper",
)

for index, chunk in enumerate(
    chunks
):
    result = await parse_chunk(
        chunk
    )

    await progress.progress(
        step_id,
        percent=(
            (index + 1)
            / len(chunks)
            * 100
        ),
        detail=(
            f"Analyzed section "
            f"{index + 1}/"
            f"{len(chunks)}"
        ),
    )

await progress.complete(
    step_id,
    summary=(
        "Capability evidence extracted"
    ),
)
```

前端只显示可观察动作，不显示隐藏 Chain-of-Thought。

---

# 14. P1：SSE Forward-Compatible Event Envelope

## 14.1 当前协议脆弱点

当前前端维护硬编码 `EVENT_TYPES`，然后逐个注册 named SSE event。新后端事件如果老前端没注册，可能完全收不到；后续 seq 变化又可能被当作 gap。

另外：

```text
unknown event
→ full hydrate
```

也会把“新版本事件”误认为“事件丢失”。

## 14.2 单一 SSE message envelope

```python
class RunEventEnvelope(BaseModel):
    version: int = 1

    id: str
    seq: int

    run_id: str
    task_id: str | None = None

    type: str
    ts: float

    payload: dict
```

编码：

```python
def encode_sse(
    event: Event,
) -> str:
    envelope = {
        "version": 1,
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

不再发送：

```text
event: message.delta
```

语义类型由 JSON `type` 承担。

## 14.3 前端 RunStream

```typescript
export interface RunEvent<
  T = unknown
> {
  version: 1;

  id: string;
  seq: number;

  run_id: string;
  task_id?: string | null;

  type: string;
  ts: number;

  payload: T;
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

## 14.4 Reducer：只有真实 gap 才 hydrate

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

  if (event.seq <= store.lastSeq) {
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

  switch (event.type) {
    case "message.started":
      // ...
      return "applied";

    case "message.delta":
      // ...
      return "applied";

    case "step.started":
      // ...
      return "applied";

    case "stream.gap":
      return "gap";

    default:
      console.debug(
        "[RunEvent] ignored",
        event.type,
      );
      return "ignored";
  }
}
```

Session：

```typescript
const result = applyRunEvent(
  event,
  runId,
);

if (result === "gap") {
  await hydrate();
}
```

---

# 15. P1：Conversation / Turn 状态模型

当前主要是：

```text
Message[]
Event[]
Approval[]
Artifact[]
```

再把 `AgentActivity` 独立挂在 transcript 底部。用户感知会像“聊天 + 调试器”。

建议变成 turn projection。

```typescript
export interface ConversationTurn {
  id: string;
  taskId?: string;

  userMessage: Message;

  assistantMessages: Message[];

  steps: AgentStep[];
  approvals: Approval[];
  artifacts: ArtifactRef[];

  status:
    | "queued"
    | "running"
    | "waiting_approval"
    | "completed"
    | "failed"
    | "cancelled";
}
```

```typescript
export interface AgentStep {
  id: string;
  taskId: string;

  kind:
    | "paper_parse"
    | "planning"
    | "tool"
    | "codegen"
    | "edit"
    | "build"
    | "test"
    | "preview";

  title: string;

  status:
    | "pending"
    | "running"
    | "completed"
    | "failed";

  detail?: string;
  summary?: string;
  percent?: number;
}
```

第一阶段可以只在前端做 projection，不必马上新增 `turns` 表。下一步再给 `messages` 增加 `task_id`，实现稳定关联。

统一 Message Parts：

```typescript
export type UIMessagePart =
  | {
      type: "text";
      text: string;
    }
  | {
      type: "step";
      stepId: string;
    }
  | {
      type: "tool";
      toolCallId: string;
    }
  | {
      type: "approval";
      approvalId: string;
    }
  | {
      type: "artifact";
      artifactId: string;
    }
  | {
      type: "error";
      message: string;
    };
```

现有 `MessageParts.tsx` 的方向可以保留，但应该真正接入 Conversation，而不是和 raw Markdown + detached AgentActivity 同时存在。



# 16. P1：前端 UI/UX 全面重构

## 16.1 当前截图的问题不是“圆角不够”

当前桌面代码固定：

```tsx
<Panel defaultSize={42}>
  <ChatPanel />
</Panel>

<Panel defaultSize={58}>
  <PreviewPanel />
</Panel>
```

因此即使 Preview 尚未生成，右边仍占 58%。这正对应当前截图中巨大的 `No live preview yet` 空白区。

同时当前页面还存在：

```text
GlobalHeader
+
ChatPanel 内部 RunHeader
+
run status
+
phase:init
+
artifact count
+
右侧 preview/sandbox status
```

信息层级过于工程化，像后台管理系统，而不是 AI workspace。

## 16.2 推荐整体布局

```text
┌──────────────────────────────────────────────────────────────┐
│ ☰ PaperForge       Run title               ● Running    ··· │
├──────────────┬───────────────────────────────┬───────────────┤
│              │                               │               │
│ Threads      │ Conversation                  │ Workbench     │
│              │                               │               │
│ Today        │ User                          │ Preview       │
│ Paper App    │ Build this paper...           │ Code          │
│              │                               │ Changes       │
│ Yesterday    │ PaperForge                    │ Tests         │
│ ...          │ ✓ Read paper                  │ Artifacts     │
│              │ ● Generating interface        │ Logs          │
│──────────────│                               │               │
│ Papers       │ Response streaming...▌        │               │
│ paper.pdf    │                               │               │
│              │        Composer               │               │
└──────────────┴───────────────────────────────┴───────────────┘
```

## 16.3 Adaptive Workbench

```typescript
export type WorkbenchMode =
  | "closed"
  | "peek"
  | "open";
```

事件策略：

```typescript
export function inferWorkbenchMode(
  current: WorkbenchMode,
  event: RunEvent,
  userPinnedClosed: boolean,
): WorkbenchMode {
  if (userPinnedClosed) {
    return "closed";
  }

  if (
    event.type === "preview.ready"
  ) {
    return "open";
  }

  if (
    event.type === "artifact.created"
    || event.type === "file.changed"
  ) {
    return (
      current === "closed"
        ? "peek"
        : current
    );
  }

  return current;
}
```

页面：

```tsx
<div
  className={cn(
    "grid h-full min-w-0",
    workbenchMode === "closed"
      ? "grid-cols-1"
      : [
          "grid-cols-",
          "[minmax(420px,0.9fr)_",
          "minmax(480px,1.1fr)]",
        ].join("")
  )}
>
  <Conversation />

  {workbenchMode !== "closed" && (
    <Workbench />
  )}
</div>
```

无 artifact / preview 时：

```text
Sidebar + centered Conversation
```

第一次产生文件：

```text
Workbench peek
```

`preview.ready`：

```text
Workbench open
```

用户手动关闭后不要自动反复抢回来。

## 16.4 Conversation 宽度

```css
.conversation-inner {
  width: min(
    calc(100% - 40px),
    800px
  );
  margin-inline: auto;
}
```

User 保留小 bubble；Assistant 不用大 Card，文本自然铺开。

## 16.5 删除重复 Run Header

全局只保留一个：

```text
PaperForge / hey                ● Running   ···
```

`run_id / phase / artifact count` 放入：

```text
Run details popover
```

不要永久占据对话上方。

## 16.6 Quick Actions 改为场景化建议

当前永久展示：

```text
Productize
Alternatives
Revise PRD
Fix build
Restart preview
```

建议：

### Empty State

```text
Productize a paper
Explore a paper
Compare multiple papers
```

### 正常 Conversation

只保留 Composer。

### Slash Command

```text
/productize
/alternatives
/revise-prd
/fix
/restart-preview
```

## 16.7 Stable React key

从：

```tsx
{messages.map((msg, i) => (
  <MessageView
    key={i}
    ...
  />
))}
```

改为：

```tsx
{messages.map((message) => (
  <MessageView
    key={
      message.public_id
      ?? message.id
    }
    message={message}
  />
))}
```

## 16.8 Memo completed messages

```tsx
export const MessageView =
  memo(
    function MessageView({
      message,
    }: {
      message: Message;
    }) {
      return (
        <article>
          <Markdown>
            {message.content}
          </Markdown>

          {message.streaming && (
            <StreamingCaret />
          )}
        </article>
      );
    },
    (prev, next) => (
      prev.message.id
        === next.message.id
      && prev.message.content
        === next.message.content
      && prev.message.status
        === next.message.status
    ),
  );
```

## 16.9 不做假打字动画

模型已经 streaming，只显示轻量 caret：

```tsx
function StreamingCaret() {
  return (
    <span
      aria-hidden
      className="
        ml-0.5
        inline-block
        h-4
        w-[2px]
        animate-pulse
        bg-current
        align-middle
      "
    />
  );
}
```

不要收到 chunk 后再逐字符播放。

## 16.10 Smart Stick-to-Bottom

当前每个 messages/events 改变都 `smooth scroll`，Streaming 会持续叠加动画。

改：

```typescript
import {
  RefObject,
  useEffect,
  useLayoutEffect,
  useRef,
} from "react";


export function useStickToBottom(
  scrollRef:
    RefObject<HTMLDivElement>,
  dependency: unknown,
) {
  const stick = useRef(true);

  useEffect(() => {
    const el = scrollRef.current;

    if (!el) return;

    const handleScroll = () => {
      const distance =
        el.scrollHeight
        - el.scrollTop
        - el.clientHeight;

      stick.current = (
        distance < 96
      );
    };

    el.addEventListener(
      "scroll",
      handleScroll,
      { passive: true },
    );

    return () => {
      el.removeEventListener(
        "scroll",
        handleScroll,
      );
    };
  }, [scrollRef]);

  useLayoutEffect(() => {
    const el = scrollRef.current;

    if (
      !el
      || !stick.current
    ) {
      return;
    }

    // Streaming 不需要 smooth。
    el.scrollTop =
      el.scrollHeight;
  }, [dependency]);

  return stick;
}
```

当用户向上滚后显示：

```text
↓ Jump to latest
```

---

# 17. P1：Workbench 重构

当前 `PreviewPanel.tsx` 已经接近 900 行，同时承担 Preview、Editor、File Tree、Changes、Tests、Artifacts、Logs 等职责。

建议拆成：

```text
web/components/workbench/

  Workbench.tsx
  WorkbenchHeader.tsx
  WorkbenchTabs.tsx
  WorkbenchEmpty.tsx

  preview/
    PreviewView.tsx
    PreviewToolbar.tsx
    PreviewFrame.tsx

  editor/
    EditorView.tsx
    EditorTabs.tsx
    FileTree.tsx
    FileTreeItem.tsx

  changes/
    ChangesView.tsx
    RevisionList.tsx
    DiffViewer.tsx

  tests/
    TestsView.tsx
    VerificationLayer.tsx

  artifacts/
    ArtifactsView.tsx
    ArtifactCard.tsx

  logs/
    LogsView.tsx

  hooks/
    useWorkbench.ts
    useEditorTabs.ts
    usePreview.ts
    useWorkspaceTree.ts
```

`Workbench.tsx`：

```tsx
export function Workbench() {
  const activeTab =
    useAppStore(
      (state) =>
        state.activeWorkbenchTab
    );

  return (
    <section
      className="
        flex min-w-0 flex-col
        border-l border-border/60
        bg-background
      "
    >
      <WorkbenchHeader />
      <WorkbenchTabs />

      <div className="min-h-0 flex-1">
        {activeTab === "preview" && (
          <PreviewView />
        )}

        {activeTab === "code" && (
          <EditorView />
        )}

        {activeTab === "changes" && (
          <ChangesView />
        )}

        {activeTab === "tests" && (
          <TestsView />
        )}

        {activeTab === "artifacts" && (
          <ArtifactsView />
        )}

        {activeTab === "logs" && (
          <LogsView />
        )}
      </div>
    </section>
  );
}
```

Preview 尚未 ready 时，默认应该是 **Workbench closed**。如果用户主动打开：

```tsx
function PreviewEmpty() {
  return (
    <div
      className="
        flex h-full
        items-center justify-center
      "
    >
      <div className="max-w-xs text-center">
        <p className="text-sm font-medium">
          Preview will appear here
        </p>

        <p
          className="
            mt-1 text-sm
            text-muted-foreground
          "
        >
          PaperForge is still
          generating and verifying
          the application.
        </p>
      </div>
    </div>
  );
}
```

不要让一个空态强行占一半以上屏幕。

---

# 18. P1：Preview Proxy / Iframe / Logs

## 18.1 Preview iframe 隔离

当前 iframe 没有 `sandbox` attribute。第一阶段至少：

```tsx
<iframe
  src={previewUrl}
  title="Generated app preview"
  sandbox="
    allow-scripts
    allow-forms
    allow-modals
    allow-popups
  "
  referrerPolicy="no-referrer"
/>
```

生产上更推荐：

```text
app.paperforge.dev

<random-id>.preview.paperforge.dev
```

让用户生成的 Next.js 应用与 PaperForge 主站分 origin。若 HMR 或某些应用能力确实需要 `allow-same-origin`，先完成 origin 隔离再放开。

## 18.2 Shared AsyncClient

FastAPI lifespan：

```python
from contextlib import (
    asynccontextmanager,
)
import httpx


@asynccontextmanager
async def lifespan(app):
    app.state.preview_http = (
        httpx.AsyncClient(
            timeout=httpx.Timeout(30),
            follow_redirects=False,
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
            ),
        )
    )

    try:
        yield
    finally:
        await (
            app.state
            .preview_http
            .aclose()
        )
```

## 18.3 Streaming proxy

```python
from fastapi.responses import (
    StreamingResponse,
)
from starlette.background import (
    BackgroundTask,
)


async def proxy_preview_request(
    request: Request,
    sandbox_id: str,
    path: str,
):
    sandbox, port = resolve_target(
        sandbox_id
    )

    target = (
        f"http://127.0.0.1:"
        f"{port}/{path}"
    )

    if request.url.query:
        target += (
            f"?{request.url.query}"
        )

    client: httpx.AsyncClient = (
        request.app.state.preview_http
    )

    headers = {
        key: value
        for key, value
        in request.headers.items()
        if key.lower()
        not in {
            "host",
            "connection",
            "content-length",
        }
    }

    upstream_request = (
        client.build_request(
            method=request.method,
            url=target,
            headers=headers,
            content=await request.body(),
        )
    )

    upstream = await client.send(
        upstream_request,
        stream=True,
    )

    response_headers = {
        key: value
        for key, value
        in upstream.headers.items()
        if key.lower()
        not in {
            "content-length",
            "connection",
            "transfer-encoding",
        }
    }

    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=(
            upstream.status_code
        ),
        headers=response_headers,
        background=BackgroundTask(
            upstream.aclose
        ),
    )
```

## 18.4 Logs 改成增量事件

不要每隔几秒重新下载整个 log。

事件：

```text
sandbox.log.delta
```

payload：

```json
{
  "sandbox_id": "sb_x",
  "stream": "stdout",
  "offset": 1234,
  "text": "Compiled successfully\n"
}
```

Backend：

```python
async def pump_process_logs(
    proc,
    emit: EventEmitter,
    sandbox_id: str,
):
    assert proc.stdout is not None

    offset = 0

    while True:
        chunk = (
            await proc.stdout.readline()
        )

        if not chunk:
            break

        text = chunk.decode(
            errors="replace"
        )

        await emit.emit(
            "sandbox.log.delta",
            {
                "sandbox_id": (
                    sandbox_id
                ),
                "stream": "stdout",
                "offset": offset,
                "text": text,
            },
        )

        offset += len(chunk)
```

Frontend：

```typescript
case "sandbox.log.delta":
  store.appendSandboxLog(
    data.sandbox_id,
    data.text,
  );
  return "applied";
```

---

# 19. P1：Verification Pipeline V2

## 19.1 不要用一个 score 同时表示技术可运行和产品完成度

建议分：

```text
Technical readiness
Product readiness
Quality score
```

Hard gates：

```python
class VerificationGate(
    BaseModel
):
    workspace_ok: bool
    build_ok: bool
    typecheck_ok: bool
    security_ok: bool

    runtime_ok: bool | None = None
    acceptance_ok: bool | None = None

    @property
    def technical_ready(
        self,
    ) -> bool:
        return all([
            self.workspace_ok,
            self.build_ok,
            self.typecheck_ok,
            self.security_ok,
        ])

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

Report：

```python
report = {
    "technical_ready": (
        gates.technical_ready
    ),

    # 可以展示 Preview，
    # 不代表产品验收通过。
    "preview_allowed": (
        gates.workspace_ok
        and gates.build_ok
    ),

    "product_ready": (
        gates.product_ready
    ),

    "quality_score": score,
}
```

UI 可以明确显示：

```text
Build        Passed
Runtime      Ready
Acceptance   3 / 5 passed
```

而不是都压成一个 `Ready`。

## 19.2 Repair 不再受 BUSINESS_FILES 限制

先根据错误定位 relevant files：

```python
def select_relevant_files(
    errors: list[str],
    workspace_tree: list[str],
) -> list[str]:
    selected: list[str] = []

    for error in errors:
        for path in workspace_tree:
            if path in error:
                selected.append(path)

    return list(
        dict.fromkeys(selected)
    )[:12]
```

再读取：

```python
context = {
    "errors": errors,
    "files": [
        {
            "path": path,
            "content": (
                workspace.read(path)
            ),
        }
        for path
        in relevant_files
    ],
}
```

LLM 输出的 patch 仍必须经过 `SafeWorkspacePolicy`。

## 19.3 Build log 实时化

```python
async def run_command_streaming(
    command: list[str],
    cwd: Path,
    on_line,
) -> int:

    proc = await (
        asyncio
        .create_subprocess_exec(
            *command,
            cwd=str(cwd),
            stdout=(
                asyncio.subprocess.PIPE
            ),
            stderr=(
                asyncio.subprocess.STDOUT
            ),
        )
    )

    assert proc.stdout is not None

    async for line in proc.stdout:
        await on_line(
            line.decode(
                errors="replace"
            )
        )

    return await proc.wait()
```

调用：

```python
step_id = await progress.start(
    kind="build",
    title="Building application",
)

async def on_build_line(
    line: str,
):
    await emit.emit(
        "build.log.delta",
        {
            "step_id": step_id,
            "text": line,
        },
    )

return_code = (
    await run_command_streaming(
        ["npm", "run", "build"],
        cwd=app_path,
        on_line=on_build_line,
    )
)

if return_code == 0:
    await progress.complete(
        step_id,
        summary="Build succeeded",
    )
```

---

# 20. P1/P2：Paper Parsing 与 Capability Contract

当前 text extraction + chunk/map-reduce 是合理基础，但“论文产品化”还需要从：

```text
论文说了什么
```

提升到：

```text
论文能提供什么可执行能力
```

## 20.1 CapabilityContract

```python
class CapabilityInput(BaseModel):
    name: str
    type: str
    required: bool = True
    description: str = ""


class CapabilityOutput(BaseModel):
    name: str
    type: str
    description: str = ""


class ImplementationReference(
    BaseModel
):
    kind: Literal[
        "github",
        "project_page",
        "dataset",
        "model",
        "api",
        "paper",
    ]

    url: str
    label: str = ""


class CapabilityContract(BaseModel):
    name: str
    description: str

    inputs: list[CapabilityInput]
    outputs: list[CapabilityOutput]

    preconditions: list[str]
    failure_modes: list[str]

    expected_latency: (
        str | None
    ) = None

    compute_requirements: list[str]

    integration_mode: Literal[
        "mock",
        "local_model",
        "remote_api",
        "unknown",
    ]

    implementation_refs: list[
        ImplementationReference
    ]

    confidence: float
```

## 20.2 不要无声截断论文

如果预算限制导致没有处理全部内容，应把 coverage 作为 artifact 的显式字段：

```python
class ParseCoverage(BaseModel):
    total_pages: int
    processed_pages: list[int]
    omitted_pages: list[int]
    complete: bool
```

如果不完整：

```json
{
  "parse_coverage": {
    "total_pages": 83,
    "processed_pages": [1, 2, 3],
    "omitted_pages": [75, 76, 77],
    "complete": false
  }
}
```

## 20.3 Adaptive Summary Tree

```python
async def summarize_tree(
    chunks: list[PaperChunk],
    llm: LLMClient,
):
    summaries = []

    for group in batched(
        chunks,
        size=6,
    ):
        summaries.append(
            await summarize_batch(
                group,
                llm,
            )
        )

    while len(summaries) > 6:
        summaries = [
            await summarize_batch(
                group,
                llm,
            )
            for group
            in batched(
                summaries,
                size=6,
            )
        ]

    return (
        await synthesize_capability(
            summaries,
            llm,
        )
    )
```



# 21. P2：Storage / Event Broker / Worker Recovery

## 21.1 EventStore 与 EventBroker 分开

当前 EventManager 同时承担：

```text
durable persistence
in-process subscribers
history cache
seq
```

建议抽象：

```python
from typing import Protocol


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

    def subscribe(
        self,
        run_id: str,
    ):
        ...
```

Local：

```python
from collections import defaultdict
import asyncio
import contextlib


class InProcessEventBroker:
    def __init__(self):
        self._subscribers = (
            defaultdict(list)
        )

    async def publish(
        self,
        event: Event,
    ) -> None:
        for queue in self._subscribers[
            event.run_id
        ]:
            with contextlib.suppress(
                asyncio.QueueFull
            ):
                queue.put_nowait(
                    event
                )

    def subscribe(
        self,
        run_id: str,
    ) -> asyncio.Queue:
        queue = asyncio.Queue(
            maxsize=1000
        )

        self._subscribers[
            run_id
        ].append(queue)

        return queue
```

单进程继续使用这个即可；需要多 worker 后再增加 Redis/Postgres 实现，不必现在就引入。

## 21.2 Task durable claim / lease

当前内存 TaskManager 在进程重启后无法继续“正在运行”的 coroutine。

建议给 `tasks` 增加：

```sql
ALTER TABLE tasks
ADD COLUMN started_at TIMESTAMP;

ALTER TABLE tasks
ADD COLUMN lease_owner TEXT;

ALTER TABLE tasks
ADD COLUMN lease_until TIMESTAMP;

ALTER TABLE tasks
ADD COLUMN attempt INTEGER
NOT NULL DEFAULT 0;
```

MVP worker claim：

```python
def claim_next_task(
    conn,
    worker_id: str,
    lease_until: str,
):
    conn.execute(
        "BEGIN IMMEDIATE"
    )

    row = conn.execute(
        """
        SELECT *
        FROM tasks
        WHERE status = 'queued'
        ORDER BY created_at ASC
        LIMIT 1
        """
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
        """,
        (
            worker_id,
            lease_until,
            row["id"],
        ),
    )

    conn.execute("COMMIT")

    return dict(row)
```

Startup reconcile：

```python
def reconcile_stale_tasks(
    storage: Storage,
) -> None:
    stale = (
        storage.list_expired_leases()
    )

    for task in stale:
        storage.update_task(
            task_id=task["id"],
            status="queued",
        )
```

这样服务重启后 UI 不会长期卡在“running”，而实际已经没有 worker。

## 21.3 Event seq 后续优化

当前每个 event 为了 per-run monotonic seq，需要事务中查 `MAX(seq)` 再 insert。第一阶段用 delta micro-batch 已能大幅降压。

如果后续并发明显增加，再引入：

```sql
CREATE TABLE run_event_cursors (
    run_id TEXT PRIMARY KEY,
    next_seq INTEGER NOT NULL
);
```

然后在事务中原子 increment。当前不建议为了理论性能先复杂化。

## 21.4 Run list filter 进入 SQL

不要：

```text
SQL LIMIT/OFFSET
→ Python 再过滤 query/archive
```

应该：

```python
def list_runs(
    self,
    *,
    query: str | None,
    archived: bool,
    limit: int,
    offset: int,
) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []

    if archived:
        clauses.append(
            "archived_at IS NOT NULL"
        )
    else:
        clauses.append(
            "archived_at IS NULL"
        )

    if query:
        clauses.append(
            "(title LIKE ? OR id LIKE ?)"
        )

        token = f"%{query}%"

        params.extend([
            token,
            token,
        ])

    where = (
        " WHERE "
        + " AND ".join(clauses)
        if clauses
        else ""
    )

    sql = f"""
        SELECT *
        FROM runs
        {where}
        ORDER BY
          COALESCE(
            last_message_at,
            updated_at
          ) DESC
        LIMIT ?
        OFFSET ?
    """

    params.extend([
        limit,
        offset,
    ])

    with self._conn() as conn:
        rows = conn.execute(
            sql,
            params,
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]
```

## 21.5 `run_id` 不需要截太短

如果没有兼容性要求，建议：

```python
run_id = (
    f"run_{uuid.uuid4().hex}"
)
```

或 ULID / UUIDv7，以免长期运行后短 ID 碰撞风险无谓增加。

---

# 22. P2：Type Safety 与 API Contract

## 22.1 前端减少 `any`

当前 session hydration、attachment、sandbox、event payload 等多处仍有 `any`。建议利用 FastAPI 自带 OpenAPI 生成 TS types。

```bash
npx openapi-typescript \
  http://localhost:8000/openapi.json \
  -o web/lib/api/schema.d.ts
```

`package.json`：

```json
{
  "scripts": {
    "api:types": "openapi-typescript http://localhost:8000/openapi.json -o lib/api/schema.d.ts"
  }
}
```

使用：

```typescript
import type {
  components,
} from "@/lib/api/schema";

export type Run =
  components["schemas"][
    "RunResponse"
  ];

export type RunState =
  components["schemas"][
    "RunStateResponse"
  ];
```

## 22.2 Event 使用 discriminated union

```typescript
interface MessageDeltaPayload {
  message_id: string;
  delta: string;
}

interface StepStartedPayload {
  step_id: string;
  task_id: string;
  kind: string;
  title: string;
}

interface RunEventBase<
  Type extends string,
  Payload,
> {
  version: 1;
  id: string;
  seq: number;
  run_id: string;
  task_id?: string | null;
  type: Type;
  ts: number;
  payload: Payload;
}

export type KnownRunEvent =
  | RunEventBase<
      "message.delta",
      MessageDeltaPayload
    >
  | RunEventBase<
      "step.started",
      StepStartedPayload
    >;
```

## 22.3 Store 拆 slices

```text
web/lib/store/
  index.ts
  run-slice.ts
  conversation-slice.ts
  task-slice.ts
  workbench-slice.ts
  ui-slice.ts
```

### Server-backed

```text
run/messages/tasks/steps/artifacts
```

### UI-only

```text
active tab
workbench mode
sidebar
draft
scroll state
```

长期可以进一步：

```text
TanStack Query = server snapshot
Zustand        = ephemeral UI + stream overlay
```

但这属于第二阶段，不是 streaming 修复的前置条件。

## 22.4 Debug events 设上限

```typescript
const MAX_DEBUG_EVENTS = 500;

addEvent: (event) =>
  set((state) => ({
    events: [
      ...state.events,
      event,
    ].slice(
      -MAX_DEBUG_EVENTS
    ),
  })),
```

否则长 session 会无限增长。

---

# 23. 测试体系

这轮重构必须测试“用户可见行为”，否则容易再次出现“代码已经有 streaming，但浏览器还是不像 streaming”。

## 23.1 Backend：micro-batch

```python
@pytest.mark.asyncio
async def test_stream_writer_coalesces_small_chunks(
    fake_storage,
    fake_emit,
):
    writer = StreamWriter(
        run_id="run_1",
        message_id="msg_1",
        storage=fake_storage,
        emit=fake_emit,
        flush_interval_s=100,
        checkpoint_interval_s=100,
        min_flush_chars=10,
    )

    for _ in range(25):
        await writer.push_text("a")

    content = await writer.finish()

    assert content == "a" * 25

    # 25 raw chunks 不应形成 25 次 durable delta。
    assert fake_emit.delta_count < 25
```

## 23.2 Partial stream recovery

```python
@pytest.mark.asyncio
async def test_partial_stream_is_recoverable(
    storage,
    fake_emit,
):
    storage.create_streaming_message(
        "run_1",
        "msg_1",
    )

    writer = StreamWriter(
        run_id="run_1",
        message_id="msg_1",
        storage=storage,
        emit=fake_emit,
        checkpoint_interval_s=0,
    )

    await writer.push_text(
        "hello"
    )
    await writer.checkpoint()

    message = storage.get_message(
        "msg_1"
    )

    assert (
        message["content"]
        == "hello"
    )

    assert (
        message["status"]
        == "streaming"
    )
```

## 23.3 Anthropic tool regression

```python
@pytest.mark.asyncio
async def test_anthropic_tool_call_not_lost(
    provider,
):
    chunks = []

    async for chunk in provider.stream(
        model="test",
        messages=[
            Message(
                role="user",
                content="Generate app",
            )
        ],
        tools=[GENERATE_TOOL],
    ):
        chunks.append(chunk)

    tool_calls = [
        call
        for chunk in chunks
        for call in (
            chunk.tool_calls or []
        )
    ]

    assert len(tool_calls) == 1
    assert (
        tool_calls[0].name
        == "generate_nextjs_app"
    )
```

## 23.4 PRD validator

```python
def test_must_feature_requires_executable_acceptance():
    with pytest.raises(
        ValidationError
    ):
        PRD(
            prd_id="prd_1",
            product_name="Demo",
            features=[
                Feature(
                    id="feature_upload",
                    name="Upload",
                    priority="must",
                )
            ],
            acceptance_criteria=[],
        )
```

## 23.5 Workspace policy

```python
@pytest.mark.parametrize(
    "path",
    [
        "../secret.txt",
        "/etc/passwd",
        "node_modules/x.js",
        ".git/config",
    ],
)
def test_workspace_policy_rejects_unsafe_paths(
    path,
):
    policy = (
        SafeWorkspacePolicy()
    )

    with pytest.raises(
        ValueError
    ):
        policy.normalize(path)
```

## 23.6 Follow-up 不重新 parse

```python
def test_existing_workspace_can_be_patched_without_reparse():
    state = WorkspaceState(
        workspace_path="/tmp/app"
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

这个测试直接代表核心产品体验：

```text
已经生成 App
→ 用户继续改 App
→ 不重新从 paper parse 开始
```

## 23.7 Frontend：unknown event 不 hydrate

```typescript
it(
  "ignores unknown future events",
  () => {
    useAppStore.setState({
      lastSeq: 10,
    });

    const result =
      applyRunEvent(
        {
          version: 1,
          id: "evt_11",
          seq: 11,
          run_id: "run_1",
          type: "future.event",
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

## 23.8 Frontend：真实 gap

```typescript
it(
  "detects real sequence gap",
  () => {
    useAppStore.setState({
      lastSeq: 10,
    });

    const result =
      applyRunEvent(
        {
          version: 1,
          id: "evt_12",
          seq: 12,
          run_id: "run_1",
          type: "message.delta",
          ts: Date.now(),
          payload: {
            message_id: "msg_1",
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

## 23.9 Playwright：完成前必须看到文本

```typescript
test(
  "assistant streams before task completes",
  async ({ page }) => {
    await page.goto(
      "/runs/run_test"
    );

    await page
      .getByPlaceholder(
        /Ask PaperForge/
      )
      .fill(
        "Explain this paper"
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

## 23.10 Reload during streaming

```typescript
test(
  "reload resumes without duplicate text",
  async ({ page }) => {
    await startLongStreamingTask(
      page
    );

    await expect(
      page.getByTestId(
        "assistant-message-current"
      )
    ).toContainText(
      "partial"
    );

    await page.reload();

    await expect(
      page.getByTestId(
        "assistant-message-current"
      )
    ).toContainText(
      "partial"
    );

    await expect(
      page.getByTestId(
        "task-status"
      )
    ).not.toHaveText(
      /error/
    );
  }
);
```

## 23.11 Scroll 不抢用户

```typescript
test(
  "manual scroll disables auto-follow",
  async ({ page }) => {
    await seedLongConversation(
      page
    );

    const scroller =
      page.getByTestId(
        "conversation-scroll"
      );

    await scroller.evaluate(
      (element) => {
        element.scrollTop = 0;
      }
    );

    await emitFakeDelta();

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

## 23.12 Follow-up queue

```typescript
test(
  "queue follow-up while agent runs",
  async ({ page }) => {
    await startLongTask(page);

    const composer =
      page.getByPlaceholder(
        /follow-up/i
      );

    await expect(
      composer
    ).toBeEnabled();

    await composer.fill(
      "Also add a history panel"
    );

    await page
      .getByRole(
        "button",
        { name: /queue/i }
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

# 24. 可观测性与性能指标

以后不要只通过“感觉卡”判断 streaming。

Backend 记录：

```text
request_received_at
task_started_at
provider_request_at
provider_first_delta_at
message_delta_emitted_at
event_persisted_at
sse_yielded_at
```

Frontend：

```text
sse_received_at
delta_buffer_flushed_at
react_visible_at
```

Metrics：

```text
provider_ttft_ms
first_visible_token_ms
provider_to_event_ms
event_persist_ms
event_to_sse_ms
sse_to_render_ms

message_delta_events_total
message_checkpoint_total

stream_rehydrate_total
stream_gap_total

build_duration_ms
preview_ready_ms
```

初始工程目标：

```text
Provider delta → SSE yield:
p95 < 100ms

SSE receive → visible render:
p95 < 50ms

First visible token:
provider TTFT + <=150ms

React streaming updates:
<= 30 updates/s/message

Unknown event:
0 forced hydrations

Reconnect:
0 duplicated characters
```

这些是下一轮目标，不是当前版本已测出的 benchmark。

---

# 25. 文档体系重构

当前 `docs/09`、`10`、`11` 更适合作为历史 review。因为其中一部分 P0，例如 durable events、cursor、state hydration、message lifecycle 已经进入代码。

建议：

```text
docs/

  architecture/
    overview.md
    realtime-protocol.md
    task-workspace-model.md
    generation-pipeline.md
    verification-pipeline.md
    preview-sandbox.md
    frontend-workbench.md

  contracts/
    run-events.md
    prd-v2.md
    workspace-plan.md
    api.md

  adr/
    0001-durable-run-events.md
    0002-provider-stream-events.md
    0003-task-resource-model.md
    0004-safe-workspace-policy.md
    0005-preview-origin-isolation.md

  reviews/
    2026-07/
      09-code-review.md
      10-code-ui-review.md
      11-codex-style-ui-plan.md
```

旧文档顶部：

```md
> Status: Historical review
> Reviewed: 2026-07-12
>
> Some recommendations have already
> been implemented.
>
> Current architecture:
> - architecture/realtime-protocol.md
> - architecture/task-workspace-model.md
> - architecture/generation-pipeline.md
```

---

# 26. 推荐 PR 顺序

## PR 0 — Correctness Hotfix

```text
Anthropic tool streaming
optimistic public_id
user message status
stable React keys
unknown event = ignored
smart scroll
debug event ring buffer
```

目标：先修 correctness 与明显体验 bug。

## PR 1 — Realtime Pipeline

```text
StreamWriter
40ms server coalesce
250ms message checkpoint
client rAF batching
latency metrics
```

目标：让聊天真正“边生成边显示”，不刷新。

## PR 2 — Event / Provider Contract

```text
ProviderStreamEvent
RunEventEnvelope v1
single SSE onmessage
EventStore/EventBroker interfaces
```

目标：让 streaming 协议成为稳定基础设施。

## PR 3 — Task / Workspace Runtime

```text
Task queue
Step
ProgressReporter
WorkspaceState
Resource Tool Gate
ApprovalPolicy
```

目标：从一次性流水线变成持续 Agent。

## PR 4 — Generation V2

```text
PRD V2
executable acceptance criteria
WorkspacePlan
SafeWorkspacePolicy

inspect_workspace
read_workspace_file
apply_workspace_patch
run_checks

multi-file generation
revision per logical edit
```

这是产品能力提升最大的一组。

## PR 5 — Conversation UX

```text
Turn timeline
inline Steps
inline Approval
floating composer
queue / interrupt
slash commands
smart scroll
memo completed messages
```

## PR 6 — Adaptive Workbench

```text
closed/peek/open
remove fixed 42/58
split PreviewPanel
preview auto-open
Code/Changes/Tests/Logs modularization
```

## PR 7 — Preview / Production Hardening

```text
shared proxy client
streaming proxy
log SSE
iframe isolation
separate preview origin
task lease/recovery
```

## PR 8 — Contract / Docs / Cleanup

```text
OpenAPI TS types
remove dead UI paths
reduce any
architecture docs
ADR
integration tests
```

---

# 27. 文件级修改清单

## Backend

### `paperforge/orchestrator/loop.py`

```text
- 移除 chunk-level message append
+ StreamWriter
+ ProviderStreamEvent
+ Resource Gate
+ ProgressReporter
```

### 新增 `paperforge/orchestrator/stream_writer.py`

```text
+ server text coalescing
+ durable checkpoint
+ finish/fail lifecycle
```

### `paperforge/orchestrator/events.py`

```text
+ Step events
+ Build/log events
+ RunEventEnvelope
→ 逐步拆 EventStore/EventBroker
```

### `paperforge/orchestrator/tasks.py`

```text
+ cancel_and_wait
+ queue
+ durable claim/lease（生产阶段）
```

### `paperforge/llm/base.py`

```text
+ ProviderStreamEvent
+ stream_events()
```

### `paperforge/llm/openai_provider.py`

```text
OpenAI stream
→ ProviderStreamEvent
```

### `paperforge/llm/anthropic_provider.py`

```text
P0 修 tool streaming
Anthropic stream
→ ProviderStreamEvent
```

### `paperforge/schemas/prd.py`

```text
+ Feature.id
+ Feature.priority
+ executable acceptance validator
```

### `paperforge/prompts/product_planner.md`

```text
与 PRD V2 完全一致
明确 feature_id / criteria / selector
```

### `paperforge/schemas/app_manifest.py`

从：

```text
精确 3 文件白名单
```

迁移为：

```text
workspace-level path policy
dependency policy
```

### `paperforge/agents/nextjs_generator.py`

```text
WorkspacePlan
logical batch generation
safe patch
revision
progress
```

### `paperforge/agents/verifier.py`

```text
technical/product readiness 分离
browser acceptance
multi-file repair
streamed build logs
```

### `paperforge/storage/db.py`

新增：

```text
update_streaming_message_content
task_steps
task lease fields
better run query
```

建议 steps 表：

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
    metadata TEXT,

    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    created_at TIMESTAMP NOT NULL
      DEFAULT CURRENT_TIMESTAMP
);
```

### `api/routes/messages.py`

```text
+ mode=start|queue|interrupt
- done → init 强制 reset
```

### `api/routes/events.py`

```text
single default SSE event
v1 envelope
保留 after_seq replay
```

### `api/routes/preview.py`

```text
shared AsyncClient
StreamingResponse
production origin validation
```

## Frontend

### `web/lib/useRunSession.ts`

```text
single onmessage
unknown ignored
only real gap hydrate
```

### `web/lib/run-events.ts`

```text
typed reducer
rAF delta buffer
step/log events
```

### 新增 `web/lib/realtime/stream-buffer.ts`

```text
requestAnimationFrame batching
```

### `web/lib/store.ts`

拆成：

```text
runSlice
conversationSlice
taskSlice
workbenchSlice
uiSlice
```

### `web/components/ChatPanel.tsx`

迁移为：

```text
Conversation
TurnList
smart auto-scroll
JumpToLatest
```

删除：

```text
duplicate RunHeader
detached AgentActivity
```

### `web/components/Composer.tsx`

```text
运行中可输入
Queue
Interrupt
optimistic public_id
user status completed
quick actions → slash
```

### `web/components/MessageView.tsx`

```text
stable id
memo
structured parts
stream caret
```

### `web/app/runs/[id]/page.tsx`

删除固定：

```text
42 / 58
```

改 adaptive workbench。

### `web/components/PreviewPanel.tsx`

逐步拆除，迁移到：

```text
components/workbench/*
```

---

# 28. 最终验收标准

## Chat / Streaming

- [ ] 用户发送后不需要刷新；
- [ ] Assistant 在 task 完成前就开始出现；
- [ ] delta 连续，无明显长时间停顿后整段跳出；
- [ ] reload/reconnect 后不重复文字；
- [ ] Stop 后 message 状态明确；
- [ ] 用户向上滚后不被抢回底部；
- [ ] 有 Jump to latest；
- [ ] completed 历史消息不随着新 delta 反复 Markdown render。

## Agent

- [ ] 用户能看到 Agent 当前做什么；
- [ ] parse / planning / generation / build / preview 有 Step；
- [ ] tool failure 有明确状态；
- [ ] approval 在对应 turn 内；
- [ ] 不展示隐藏 chain-of-thought；
- [ ] 长 tool 执行仍有进度。

## Follow-up

- [ ] Agent running 时 composer 可输入；
- [ ] 可 queue；
- [ ] 可 interrupt & send；
- [ ] 已有 workspace 时直接修改；
- [ ] 不重新 parse paper；
- [ ] 修改后自动 typecheck/build。

## Generation

- [ ] 不再只生成 3 个业务文件；
- [ ] 支持 routes/components/hooks/types/adapters；
- [ ] 所有写入仍受 SafeWorkspacePolicy；
- [ ] 每次逻辑修改产生 revision；
- [ ] repair 可修改实际报错文件；
- [ ] Must feature 必须有 executable criterion；
- [ ] Browser smoke 真正执行 Must-have。

## UI

- [ ] 无 preview 时右侧不再占 58%；
- [ ] 只有一个 Run top bar；
- [ ] phase/id/debug metadata 不永久抢占视觉；
- [ ] Quick Actions 不永久堆在 Composer 上；
- [ ] Agent Steps 与当前 turn 一体；
- [ ] Workbench 支持 closed / peek / open；
- [ ] Preview ready 后自然打开；
- [ ] 用户手动关闭后不反复抢焦点；
- [ ] Code / Changes / Tests / Logs 模块独立。

## Runtime

- [ ] unknown event 不 full hydrate；
- [ ] real seq gap 才 hydrate；
- [ ] Anthropic tool call 不丢；
- [ ] OpenAI/Anthropic 使用 normalized stream；
- [ ] preview proxy 不全量 buffer；
- [ ] logs 不 full polling；
- [ ] backend restart 后不会永久遗留 running task。

---

# 29. 参考项目

这里建议借“交互和边界”，不是把 PaperForge 直接改成其他框架的 clone。

## OpenAI Codex

重点参考：

```text
Conversation = command plane
Diff/Changes = work surface
任务过程可审阅
Workspace 与聊天协同
```

官方：

- https://openai.com/index/introducing-the-codex-app/

## assistant-ui

适合参考：

```text
Thread
Message
Composer
Auto-scroll
Attachments
Tool UI
Approval UI
Retry
```

- https://github.com/assistant-ui/assistant-ui

不建议第一阶段直接迁移整个 UI，只借 primitives 和 streaming UX。

## AG-UI

适合参考：

```text
lifecycle events
text events
tool events
state/activity events
```

- https://docs.ag-ui.com/
- https://github.com/ag-ui-protocol/ag-ui

PaperForge 已有 durable event system，没必要强行换协议，主要参考 taxonomy 与 presentation。

## Vercel AI SDK

适合参考：

```text
UIMessage
message parts
stream protocol
typed tool parts
```

- https://ai-sdk.dev/docs/reference/ai-sdk-ui/ui-message
- https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol

## next-forge

适合参考生成应用的 production-grade 项目组织、类型边界和 design-system 思路，但不建议直接把生成物升级成完整 Turborepo。

- https://github.com/vercel/next-forge

---

# 30. 审查依据

本方案按 2026-08-10 当前 `main` 重新核对，重点包括：

## Repository

- https://github.com/Vincent-Wenhan/PaperForge

## Realtime / Orchestrator

- `paperforge/orchestrator/loop.py`
- `paperforge/orchestrator/events.py`
- `paperforge/orchestrator/tasks.py`
- `paperforge/storage/db.py`
- `api/routes/events.py`
- `api/routes/messages.py`

## Providers

- `paperforge/llm/base.py`
- `paperforge/llm/openai_provider.py`
- `paperforge/llm/anthropic_provider.py`

## Planning / Generation / Verification

- `paperforge/agents/product_planner.py`
- `paperforge/agents/nextjs_generator.py`
- `paperforge/agents/verifier.py`
- `paperforge/schemas/prd.py`
- `paperforge/schemas/app_manifest.py`
- `paperforge/prompts/product_planner.md`
- `paperforge/prompts/nextjs_generator.md`

## Frontend

- `web/app/runs/[id]/page.tsx`
- `web/components/ChatPanel.tsx`
- `web/components/Composer.tsx`
- `web/components/MessageView.tsx`
- `web/components/MessageParts.tsx`
- `web/components/PreviewPanel.tsx`
- `web/components/ConsoleLogs.tsx`
- `web/lib/store.ts`
- `web/lib/run-events.ts`
- `web/lib/useRunSession.ts`
- `web/lib/api.ts`

---

# 附录 A：推荐的新目录结构

```text
paperforge/
├── agents/
│   ├── paper_parser.py
│   ├── product_planner.py
│   ├── workspace_planner.py
│   ├── workspace_generator.py
│   └── verifier.py
│
├── llm/
│   ├── base.py
│   ├── provider_events.py
│   ├── openai_provider.py
│   └── anthropic_provider.py
│
├── orchestrator/
│   ├── loop.py
│   ├── stream_writer.py
│   ├── progress.py
│   ├── tool_policy.py
│   ├── task_queue.py
│   ├── event_store.py
│   ├── event_broker.py
│   └── events.py
│
├── workspace/
│   ├── policy.py
│   ├── workspace.py
│   ├── patches.py
│   ├── revisions.py
│   └── context.py
│
└── schemas/
    ├── capability_contract.py
    ├── prd.py
    ├── workspace_plan.py
    ├── run_event.py
    └── verification.py
```

Frontend：

```text
web/
├── components/
│   ├── conversation/
│   │   ├── Conversation.tsx
│   │   ├── TurnList.tsx
│   │   ├── Turn.tsx
│   │   ├── MessageView.tsx
│   │   ├── StepList.tsx
│   │   ├── StepRow.tsx
│   │   ├── ApprovalPart.tsx
│   │   ├── ArtifactPart.tsx
│   │   ├── JumpToLatest.tsx
│   │   └── Composer.tsx
│   │
│   ├── workbench/
│   │   ├── Workbench.tsx
│   │   ├── WorkbenchTabs.tsx
│   │   ├── preview/
│   │   ├── editor/
│   │   ├── changes/
│   │   ├── tests/
│   │   ├── artifacts/
│   │   └── logs/
│   │
│   └── shell/
│       ├── AppShell.tsx
│       ├── RunTopBar.tsx
│       └── Sidebar.tsx
│
├── lib/
│   ├── api/
│   │   ├── client.ts
│   │   └── schema.d.ts
│   │
│   ├── realtime/
│   │   ├── run-stream.ts
│   │   ├── run-events.ts
│   │   └── stream-buffer.ts
│   │
│   └── store/
│       ├── index.ts
│       ├── run-slice.ts
│       ├── conversation-slice.ts
│       ├── task-slice.ts
│       ├── workbench-slice.ts
│       └── ui-slice.ts
```

---

# 附录 B：推荐完整事件 Taxonomy

```text
run.updated

task.queued
task.started
task.completed
task.failed
task.cancelled

message.started
message.delta
message.completed
message.failed

step.started
step.progress
step.completed
step.failed

tool.started
tool.completed
tool.failed

approval.requested
approval.resolved

artifact.created
artifact.updated

workspace.revision.created
file.changed

build.started
build.log.delta
build.completed
build.failed

test.started
test.completed
test.failed

sandbox.started
sandbox.log.delta
sandbox.stopped
sandbox.failed

preview.ready
preview.stopped

stream.gap
```

统一 envelope：

```json
{
  "version": 1,
  "id": "evt_...",
  "seq": 932,
  "run_id": "run_...",
  "task_id": "task_...",
  "type": "step.progress",
  "ts": 1786356000.123,
  "payload": {
    "step_id": "step_...",
    "percent": 62,
    "detail": "Generating components"
  }
}
```

---

# 附录 C：Approval Policy

当前 `generate_nextjs_app`、sandbox、repair 等多个动作都属于 dangerous tool，会频繁打断 end-to-end workflow。建议把“危险”从工具名常量升级成风险等级。

```python
from dataclasses import dataclass
from typing import Literal


ApprovalMode = Literal[
    "always_ask",
    "trusted_workspace",
    "manual",
]


@dataclass
class ApprovalContext:
    mode: ApprovalMode
    workspace_isolated: bool
    network_allowed: bool


def should_require_approval(
    tool: ToolSpec,
    context: ApprovalContext,
) -> bool:

    if (
        context.mode
        == "always_ask"
    ):
        return (
            tool.risk != "read"
        )

    if (
        context.mode
        == "manual"
    ):
        return False

    # trusted_workspace
    if tool.risk == "read":
        return False

    if (
        tool.risk
        == "workspace_write"
        and context.workspace_isolated
    ):
        return False

    if (
        tool.risk
        == "sandbox_exec"
        and context.workspace_isolated
    ):
        return False

    if tool.risk in {
        "network",
        "destructive",
    }:
        return True

    return True
```

UI：

```text
PaperForge wants to access the network

npm install <dependency>

[Allow once]
[Always allow in this run]
[Deny]
```

而不是每个隔离 workspace 内部写入都弹一次。

---

# 附录 D：UI Design Tokens

不要依赖“大量 1px border”建立层级。

```css
:root {
  --pf-radius-xs: 6px;
  --pf-radius-sm: 8px;
  --pf-radius-md: 12px;
  --pf-radius-lg: 16px;

  --pf-border:
    color-mix(
      in oklab,
      currentColor 11%,
      transparent
    );

  --pf-surface-subtle:
    color-mix(
      in oklab,
      Canvas 97%,
      currentColor 3%
    );

  --pf-surface-raised:
    color-mix(
      in oklab,
      Canvas 94%,
      currentColor 6%
    );

  --pf-shadow-composer:
    0 8px 28px
      rgb(0 0 0 / 0.07);

  --pf-motion-fast: 120ms;
  --pf-motion-normal: 180ms;
}
```

Composer：

```css
.composer-shell {
  border:
    1px solid
    var(--pf-border);

  border-radius:
    var(--pf-radius-lg);

  background:
    var(--background);

  box-shadow:
    var(--pf-shadow-composer);

  transition:
    border-color
      var(--pf-motion-fast),
    box-shadow
      var(--pf-motion-fast);
}

.composer-shell:focus-within {
  border-color:
    color-mix(
      in oklab,
      currentColor 22%,
      transparent
    );

  box-shadow:
    0 10px 32px
      rgb(0 0 0 / 0.09);
}
```

---

# 附录 E：最终优先级

如果资源有限，优先不要做“更漂亮的 Preview Tabs”。

建议严格按：

```text
1. Streaming hot path
2. Anthropic tool correctness
3. PRD acceptance contract
4. Multi-file workspace generation
5. Resource-based iterative editing
6. Queue / Interrupt
7. Observable Agent Steps
8. Adaptive Workbench
9. Preview / Logs / production hardening
```

PaperForge 真正达到 ChatGPT / Codex 那种“丝滑”的关键不是圆角和配色本身，而是：

```text
输入不会被锁死
回复马上出现
Agent 做什么实时可见
结果可以连续修改
修改能够实时验证
工作区只在需要时出现
断线/刷新不会丢状态
```

在这些成立后，再统一视觉 token、间距、动画、字体、icon 和 hover/focus 状态，UI 才会从“看起来像 Agent 产品”变成“实际用起来像 Agent 产品”。
