# PaperForge 深度优化实施规格

> 日期：2026-08-14  
> 状态：待实施  
> 目标读者：负责实现 PaperForge 前端、后端与 Agent 工作流的 Coding Agent / 工程师  
> 范围：实时会话、ChatGPT/Codex 风格交互、代码工作台、会话管理、文献管理、Agent 工作流、生成质量、验证评测、文档与 CI  
> 原则：复用已有架构，优先修通主链，不进行无证据的大重写

---

## 0. 文档目的

本文不是产品愿景文档，而是一份可以直接执行的工程实施规格。它需要解决以下事实问题：

1. 后端已经完成并持久化模型回复，SSE 也发送成功，但当前会话不显示回复，刷新后才出现。
2. 聊天区域没有正确占满视口，Composer 悬在中上部，交互不像成熟对话产品。
3. Task、Step、Tool、Artifact、Workspace 已有模块，但它们没有在用户可理解的时间线中形成统一工作流。
4. 代码查看、修改、diff、验证、预览之间缺乏闭环。
5. 会话和文献管理已有基础 CRUD，但缺乏项目化组织、搜索、关联和证据追踪。
6. 后端测试数量很多，但真实论文到真实可运行产品的完整流水线尚未被端到端证明。
7. 当前生成器天然偏向 mock UI Demo，缺少确定性的产品设计、垂直切片生成和产品质量门禁。

实施完成后的目标不是“页面更好看”，而是：

```text
用户上传/选择论文
→ 在同一会话中提出目标
→ 立即看到 Agent 响应和工作进度
→ 看到每次工具调用、文件变更、验证结果
→ 在右侧工作台预览、查看 diff、编辑代码
→ Agent 基于现有工作区继续修改
→ 刷新、重连、切换会话后状态保持一致
→ 最终产物通过真实构建和浏览器验收
```

---

## 1. 已确认的当前状态

### 1.1 可以保留的基础设施

以下能力已经存在，原则上不重写：

- FastAPI API 与 SQLite 持久化。
- Run、Task、Step、Message、Approval、Artifact、Sandbox、Workspace revision 数据模型。
- Provider-neutral 流式事件。
- SSE 持久化、seq cursor、重放和 gap hydration。
- 前端 requestAnimationFrame delta buffer。
- Generation V3、SafeWorkspacePolicy、构建、验证、修复与沙箱模块。
- Next.js 前端、Zustand 状态、Monaco、Preview/Code/Changes/Tests/Artifacts/Logs 工作台骨架。
- 会话创建、重命名、置顶、归档、删除。
- 文献上传、重命名、下载、删除和 Capability Card 展示。

### 1.2 已复现的 P0 根因

当前发送消息后的实时链路为：

```text
Composer optimistic user message（没有 task_id）
→ POST /messages 返回 message + task_id，但前端忽略返回值
→ 后端创建 Task
→ Orchestrator 发 message.started(task_id=真实 Task)
→ 前端创建 assistant message(task_id=真实 Task)
→ projectTurns 只遍历 store.tasks
→ store.tasks 中没有新 Task
→ assistant message 属于未知 task_id，未被投影
→ 页面不显示
→ 刷新后 /state 返回 Task
→ 页面显示完整回复
```

修复时不得只增加一次 `refresh()`。正确修复必须让实时状态本身完备，并保留重放、乱序和重连能力。

### 1.3 自动化现状

- 后端：210 个测试通过，但有大量弃用 warning。
- 前端：52 个测试中有 1 个失败。
- Next production build 通过。
- 当前名为 full pipeline 的测试使用 Mock LLM，核心测试直接调用 `finish`，不是真正的全链路产品化测试。
- 现有 Playwright streaming 用例主要 mock `/state`，没有覆盖“发送新消息后 Task 尚未 hydration”的真实故障。

---

## 2. 实施原则与非目标

### 2.1 原则

1. **先正确，后美化**：PR-1 必须先修实时状态，再进行视觉重构。
2. **服务端持久状态为真相源**：Message、Task、Step、Artifact、Approval 的最终状态来自服务端。
3. **客户端允许 optimistic，但必须对账**：所有临时 ID 最终都要与服务端实体合并。
4. **事件必须可重放**：影响用户可见状态的事件先持久化，再广播。
5. **乱序安全**：Task、Message、Step 到达顺序不能影响最终投影。
6. **Run 是持久会话，Task 是单次用户工作单元**。
7. **Agent 使用确定性骨架，模型负责局部推理**，不让单个 Orchestrator Prompt 自由控制整个质量链。
8. **每个阶段有真实验收证据**，不能只用 mock 单元测试宣称完成。
9. **增量提交**：每个 PR 可独立合并、回滚和验收。

### 2.2 非目标

本轮不做：

- 替换 FastAPI、SQLite、Next.js、Zustand 或整个 Orchestrator 框架。
- 为尚不存在的多机规模提前引入 Kafka 等复杂基础设施。
- 一次性创建庞大 Design System。
- 在没有评测集前仅靠换模型解决生成质量。
- 直接复制 ChatGPT/Codex 的品牌视觉或专有资产。

---

## 3. 目标架构

### 3.1 领域层级

```text
Run / Conversation
├── attached papers
├── Task / Turn 1
│   ├── user message
│   ├── assistant messages
│   ├── tool activities
│   ├── steps
│   ├── approvals
│   ├── artifacts
│   └── change sets
├── Task / Turn 2
└── current workspace / preview
```

### 3.2 前端布局

```text
┌──────────────────────── Global Header ─────────────────────────┐
│ App / current conversation / connection / commands / settings │
├──────── Sidebar ────────┬──────── Conversation ───────┬────────┤
│ New conversation       │ Turn 1                       │ Work-  │
│ Search                 │ Turn 2                       │ bench  │
│ Pinned / Recent        │ Current streaming turn       │ Preview│
│ Projects               │                              │ Code   │
│ Papers                 │ Sticky Composer              │ Diff   │
└────────────────────────┴──────────────────────────────┴────────┘
```

桌面端支持拖拽分栏；平板端在 Chat/Workbench 间切换；手机端 Sidebar 使用抽屉，Workbench 使用全屏 sheet。

### 3.3 实时状态路径

```text
DB transaction
→ persist entity
→ persist RunEvent(seq)
→ broadcast SSE
→ frontend event reducer
→ normalized entity store
→ derived conversation projection
→ component-level subscription
```

快照 hydration 与事件 reducer 必须写入同一套 normalized store，禁止维护两套含义不同的数据。

---

## 4. PR-0：建立基线与 CI 门禁

### 4.1 目标

在修改业务代码前建立可重复基线，防止“文档全部勾选但真实体验仍失败”。

### 4.2 修改内容

1. 修复 `web/lib/__tests__/run-events.test.ts` 中 `ignored/unknown` 契约不一致。
2. 修复 PreviewPanel 测试中的 React `act()` warning。
3. CI 明确运行：

```bash
python -m ruff check .
python -m pytest -q
cd web && npm test -- --run
cd web && npm run build
cd web && npm run test:e2e
```

4. 增加 `docs/capability-matrix.md`，使用六级状态：

```text
designed
implemented
wired
mock-tested
real-model-verified
production-ready
```

5. 禁止人工把 capability 直接标记为 production-ready；必须附测试或真实运行证据链接。

### 4.3 Definition of Done

- 所有现有前后端测试全绿。
- 测试输出没有 React state update warning。
- Next build 可重复执行。
- CI 失败会阻止合并。

---

## 5. PR-1：实时 Task/Message 主链修复

这是最高优先级，其他 UI 工作必须在本 PR 后进行。

### 5.1 API 返回完整创建结果

#### 新契约

`POST /api/runs/{run_id}/messages` 返回：

```json
{
  "status": "queued",
  "run_id": "run_x",
  "message": {
    "id": 149,
    "public_id": "client_uuid",
    "task_id": "task_x",
    "role": "user",
    "content": "...",
    "status": "completed"
  },
  "task": {
    "id": "task_x",
    "run_id": "run_x",
    "status": "queued",
    "phase": "init"
  },
  "event_cursor": 42
}
```

不要只返回 `task_id`。

#### Pydantic 模型示例

```python
# api/routes/messages.py
from pydantic import BaseModel

class MessageCreateResult(BaseModel):
    status: str
    run_id: str
    message: dict
    task: dict
    event_cursor: int


@router.post("/{run_id}/messages", response_model=MessageCreateResult)
async def send_message(run_id: str, req: MessageCreate) -> MessageCreateResult:
    ...
    return MessageCreateResult(
        status="queued",
        run_id=run_id,
        message=message,
        task=task,
        event_cursor=storage.get_max_event_seq(run_id),
    )
```

### 5.2 Message + Task 必须原子创建

当前先插 Message 再插 Task，任一步失败都会留下不完整关系。新增 Storage 方法：

```python
from dataclasses import dataclass
from datetime import UTC, datetime
import uuid

@dataclass(frozen=True)
class CreatedUserTask:
    message: dict[str, object]
    task: dict[str, object]


def create_user_task(
    self,
    *,
    run_id: str,
    content: str,
    public_id: str | None,
    phase: str,
    priority: int,
) -> CreatedUserTask:
    task_id = f"task_{uuid.uuid4().hex}"
    now = datetime.now(UTC).isoformat()

    with self._lock, self._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            message_cursor = conn.execute(
                """
                INSERT INTO messages (
                    public_id, run_id, role, content,
                    status, task_id, created_at
                ) VALUES (?, ?, 'user', ?, 'completed', ?, ?)
                """,
                (public_id, run_id, content, task_id, now),
            )
            message_id = int(message_cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO tasks (
                    id, run_id, title, goal, status, phase,
                    priority, user_message_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    run_id,
                    content.strip()[:120] or "Productization task",
                    content,
                    phase,
                    priority,
                    message_id,
                    now,
                    now,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return CreatedUserTask(
        message=self.get_message(message_id),
        task=self.get_task(task_id),
    )
```

如果 `Storage._conn()` 已经隐式管理事务，应按现有连接实现调整，但必须保留同一事务边界。

### 5.3 Task 生命周期事件

#### 统一事件类型

```python
TaskStatus = Literal[
    "queued",
    "running",
    "waiting_user",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
]
```

在 `EventEmitter` 增加：

```python
async def task_created(self, task: dict[str, Any]) -> None:
    await self.emit(
        "task.created",
        {"task": task},
        task_id=task["id"],
    )

async def task_updated(self, task: dict[str, Any]) -> None:
    await self.emit(
        "task.updated",
        {"task": task},
        task_id=task["id"],
    )

async def task_completed(self, task: dict[str, Any]) -> None:
    await self.emit(
        "task.completed",
        {"task": task},
        task_id=task["id"],
    )
```

不要让 payload 同时有散落的 `task_id/status/phase` 和嵌套 Task 两种格式。新事件统一使用 `{ "task": serialized_task }`，旧 `task.phase.changed` 保留一个兼容周期。

#### 统一状态更新服务

新增一个负责持久化并发事件的服务，避免各处直接更新 Task：

```python
class TaskLifecycleService:
    def __init__(self, storage: Storage, emitter: EventEmitter) -> None:
        self.storage = storage
        self.emitter = emitter

    async def transition(
        self,
        task_id: str,
        *,
        status: str | None = None,
        phase: str | None = None,
    ) -> dict[str, Any]:
        task = await asyncio.to_thread(
            self.storage.update_task,
            task_id=task_id,
            status=status,
            phase=phase,
        )
        if task is None:
            raise LookupError(f"Task not found: {task_id}")
        await self.emitter.task_updated(task)
        return task
```

Orchestrator、Queue、Cancel API、Approval checkpoint 都使用它。

### 5.4 事件顺序

创建消息后的最低保证顺序：

```text
task.created
run.updated（如标题变化）
task.updated(status=running)
run.status.changed
run.started
message.started
message.delta...
message.completed / message.failed
task.completed / task.failed
run.updated(status=active/error)
run.finished / run.error
```

所有事件使用同一 run seq。事件到达前实体已经写入数据库。

### 5.5 前端类型

补全 API 类型，删除该主链上的 `any`：

```typescript
export interface SendMessageResult {
  status: "queued";
  run_id: string;
  message: Message;
  task: Task;
  event_cursor: number;
}

export type TaskEventPayload = { task: Task };

export type KnownRunEvent =
  | RunEventBase<"task.created", TaskEventPayload>
  | RunEventBase<"task.updated", TaskEventPayload>
  | RunEventBase<"task.completed", TaskEventPayload>
  | RunEventBase<"message.started", { message_id: string }>
  | RunEventBase<"message.delta", MessageDeltaPayload>
  | RunEventBase<"message.completed", { message_id: string; content: string }>
  | RunEventBase<"message.failed", { message_id: string; error: string }>
  | RunEventBase<string, unknown>;
```

### 5.6 前端发送后立即对账

```typescript
const optimisticId = crypto.randomUUID();

addMessage({
  id: optimisticId,
  public_id: optimisticId,
  role: "user",
  content,
  status: "sending",
  streaming: false,
});

try {
  const result = await api.sendMessage(
    currentRun.id,
    content,
    paperIds,
    optimisticId,
    mode,
  );

  reconcileMessage(optimisticId, {
    ...result.message,
    id: result.message.public_id ?? String(result.message.id),
  });
  upsertTask(result.task);
  setLastSeq(result.event_cursor);
  clearAttachments();
  setInput("");
} catch (error) {
  markMessageFailed(optimisticId, toUserMessage(error));
}
```

注意：失败时不要直接删除用户消息。成熟产品应保留红色失败状态并提供“重试”。

### 5.7 Store 正规化与乱序容错

短期可继续使用数组，但增加以下动作：

```typescript
upsertTask(task: Task): void;
reconcileMessage(optimisticId: string, serverMessage: Message): void;
upsertMessage(message: Message): void;
ensureSyntheticTask(taskId: string, runId: string): void;
setConnectionState(state: ConnectionState): void;
```

推荐逐步改为 ID map：

```typescript
interface EntityState {
  tasksById: Record<string, Task>;
  taskOrder: string[];
  messagesById: Record<string, Message>;
  messageOrder: string[];
  stepsById: Record<string, AgentStep>;
  approvalsById: Record<string, Approval>;
  artifactsById: Record<string, Artifact>;
}
```

如果本轮不做完整正规化，也必须避免重复实体并保证 optimistic ID 合并。

### 5.8 reducer 处理 Task 事件

```typescript
case "task.created":
case "task.updated":
case "task.completed": {
  const task = data.task as Task | undefined;
  if (task?.id) store.upsertTask(task);
  return "applied";
}

case "message.started": {
  const resolvedTaskId = taskId ?? "untracked";
  if (resolvedTaskId !== "untracked") {
    store.ensureSyntheticTask(resolvedTaskId, runId);
  }
  store.upsertMessage({
    id: data.message_id,
    public_id: data.message_id,
    role: "assistant",
    content: "",
    streaming: true,
    status: "streaming",
    task_id: resolvedTaskId,
  });
  return "applied";
}
```

### 5.9 delta buffer 保留 task_id

不要让 `message.delta` 在 `message.started` 乱序时创建一个没有 task_id 的 placeholder。

```typescript
type PendingDelta = {
  messageId: string;
  taskId?: string;
  text: string;
};

export function enqueueMessageDelta(
  messageId: string,
  delta: string,
  taskId?: string,
) {
  const pending = buffer.get(messageId) ?? { messageId, taskId, text: "" };
  pending.taskId ||= taskId;
  pending.text += delta;
  buffer.set(messageId, pending);
  scheduleFlush();
}
```

Store 的 `appendMessageDelta` 同样接受 taskId。

### 5.10 projectTurns 不能丢实体

使用 Task 顺序 + 未知 task_id 顺序共同投影：

```typescript
const knownTaskIds = new Set(tasks.map((task) => task.id));
const inferredTaskIds: string[] = [];

for (const message of messages) {
  if (
    message.task_id &&
    message.task_id !== "untracked" &&
    !knownTaskIds.has(message.task_id) &&
    !inferredTaskIds.includes(message.task_id)
  ) {
    inferredTaskIds.push(message.task_id);
  }
}

const allTasks = [
  ...tasks,
  ...inferredTaskIds.map((id) => ({
    id,
    task_id: id,
    status: "queued",
    title: "Preparing task",
    synthetic: true,
  })),
];
```

`untracked` 只用于真正没有 task_id 的历史数据。

### 5.11 SSE 连接状态

新增：

```typescript
export type ConnectionState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "offline"
  | "error";

class SSEClient {
  onConnectionChange(handler: (state: ConnectionState) => void) {
    this.connectionHandler = handler;
  }

  connect(...) {
    this.connectionHandler?.("connecting");
    this.es = new EventSource(...);
    this.es.onopen = () => this.connectionHandler?.("connected");
    this.es.onerror = () => this.connectionHandler?.("reconnecting");
  }
}
```

GlobalHeader 必须显示真实连接状态，不再由 `loading/error` 推算。

### 5.12 必须新增的测试

#### 前端 reducer

- task.created 会 upsert Task。
- message.started 在 task.created 之前也可见。
- delta 在 message.started 之前不会丢 task_id。
- optimistic user message 被服务端消息合并，不产生两条。
- unknown future event 返回统一的 `ignored`。

#### API/Storage

- Message + Task 创建要么都成功，要么都失败。
- `public_id` 幂等重试不会重复创建 Message/Task。
- task 生命周期事件持久化并按 seq 排序。

#### 真实 Playwright

不 mock `/state`，使用本地测试 provider：

```typescript
test("new assistant reply appears without reload", async ({ page }) => {
  const run = await createTestRun();
  await page.goto(`/runs/${run.id}`);

  await page.getByPlaceholder(/Ask PaperForge/i).fill("stream-test");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("stream-test-response")).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByTestId("task-status")).toContainText("completed");
});
```

### 5.13 PR-1 Definition of Done

- 发送消息后无需刷新即可看到第一个 token 和最终回复。
- 刷新前后 Turn 数量、Message 数量和顺序完全一致。
- 快速切换会话时不会串消息。
- SSE 重连不会重复字符。
- 新 Task 不会产生未知 task_id 的静默丢失。
- Stop、Queue、Interrupt 后 Task 状态实时更新。

---

## 6. PR-2：AppShell、聊天布局与 Composer

### 6.1 重构目标

ChatGPT/Codex 风格来自稳定的信息层级和交互反馈，不是简单改配色。

需要形成：

- 固定 Header。
- 可折叠 Sidebar。
- 中间聊天完整占高。
- Composer 固定在底部。
- 右侧 Workbench 可拖拽。
- 每个区域只维护自己的滚动容器。

### 6.2 新组件结构

```text
web/components/shell/
├── AppShell.tsx
├── GlobalHeader.tsx
├── DesktopSidebar.tsx
├── MobileSidebar.tsx
├── ConversationPane.tsx
├── WorkbenchPane.tsx
└── ConnectionIndicator.tsx
```

### 6.3 AppShell 示例

复用现有 `react-resizable-panels`：

```tsx
export function AppShell({ sidebar, conversation, workbench }: Props) {
  const workbenchMode = useAppStore((s) => s.workbenchMode);

  return (
    <div className="h-dvh min-h-0 overflow-hidden bg-background text-foreground">
      <GlobalHeader />
      <div className="flex h-[calc(100dvh-var(--header-height))] min-h-0">
        {sidebar}
        <PanelGroup direction="horizontal" className="min-w-0 flex-1">
          <Panel defaultSize={workbenchMode === "closed" ? 100 : 54} minSize={34}>
            <div className="h-full min-h-0 overflow-hidden">{conversation}</div>
          </Panel>
          {workbenchMode !== "closed" && (
            <>
              <PanelResizeHandle className="group w-1 bg-border hover:bg-primary/40" />
              <Panel defaultSize={46} minSize={28} maxSize={66}>
                <div className="h-full min-h-0 overflow-hidden">{workbench}</div>
              </Panel>
            </>
          )}
        </PanelGroup>
      </div>
    </div>
  );
}
```

CSS：

```css
:root {
  --header-height: 48px;
  --sidebar-width: 272px;
  --conversation-max-width: 820px;
  --composer-max-width: 820px;
}

html,
body {
  height: 100%;
  overflow: hidden;
}
```

### 6.4 ChatPanel 正确占高

ChatPanel 根元素必须有 `h-full min-h-0`：

```tsx
return (
  <section className="relative flex h-full min-h-0 flex-col overflow-hidden">
    <ConversationViewport />
    <ComposerDock />
  </section>
);
```

ConversationViewport：

```tsx
<div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
  <div className="mx-auto w-full max-w-[var(--conversation-max-width)] px-4 pb-8 pt-6">
    {turns.map((turn) => <ConversationTurnView key={turn.id} turn={turn} />)}
    <div ref={bottomSentinelRef} aria-hidden className="h-px" />
  </div>
</div>
```

### 6.5 智能滚动

使用底部 sentinel，不要每次 delta 都直接设置 `scrollTop`：

```typescript
useEffect(() => {
  const root = scrollRef.current;
  const target = bottomSentinelRef.current;
  if (!root || !target) return;

  const observer = new IntersectionObserver(
    ([entry]) => setIsAtBottom(entry.isIntersecting),
    { root, threshold: 0.98 },
  );
  observer.observe(target);
  return () => observer.disconnect();
}, []);

useLayoutEffect(() => {
  if (isAtBottom && activeMessageId) {
    bottomSentinelRef.current?.scrollIntoView({ block: "end" });
  }
}, [activeMessageId, activeMessageText, isAtBottom]);
```

用户向上滚动后停止自动跟随，显示浮动按钮：

```tsx
{!isAtBottom && (
  <button className="absolute bottom-28 left-1/2 ..." onClick={scrollToBottom}>
    跳到最新
  </button>
)}
```

### 6.6 Composer 设计

主界面只保留一个视觉主按钮。Queue/Interrupt 使用二级菜单：

```text
idle:       Send
running:    Stop
input while running:
  Enter     Queue after current task
  menu      Interrupt current task and send
```

建议结构：

```tsx
<div className="shrink-0 border-t bg-background/95 px-4 pb-4 pt-3 backdrop-blur">
  <form className="mx-auto max-w-[var(--composer-max-width)] rounded-2xl border bg-surface shadow-sm">
    <AttachmentStrip />
    <textarea ... />
    <div className="flex items-center justify-between px-2 pb-2">
      <ComposerActions />
      <SendOrStopButton />
    </div>
  </form>
</div>
```

发送失败时保留消息并提供：

```text
发送失败 · 重试 · 编辑
```

### 6.7 视觉 Token

仅建立小型 Token 层：

```css
:root {
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 16px;
  --surface-raised: 0 0% 100%;
  --surface-hover: 240 5% 96%;
  --shadow-float: 0 8px 30px rgb(0 0 0 / 0.08);
  --motion-fast: 120ms;
  --motion-normal: 180ms;
}
```

尊重：

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

### 6.8 PR-2 Definition of Done

- 1280×720 下 Composer 位于视口底部，不存在大片错误空白。
- Chat、Sidebar、Workbench 各自滚动，不推动整个页面。
- Workbench 可拖拽，刷新后保留宽度。
- 用户上滚时 streaming 不抢滚动位置。
- 键盘、移动端、reduced motion 可用。

---

## 7. PR-3：统一 Conversation Turn 与 Agent Activity

### 7.1 用户可见模型

每个 Task 对应一个 Turn：

```typescript
interface ConversationTurnViewModel {
  id: string;
  status: TaskStatus;
  userMessage: Message | null;
  assistantMessages: Message[];
  activities: ActivityItem[];
  artifacts: Artifact[];
  changeSets: ChangeSetSummary[];
  startedAt?: string;
  completedAt?: string;
}

type ActivityItem =
  | { type: "step"; step: AgentStep }
  | { type: "tool"; call: ToolActivity }
  | { type: "approval"; approval: Approval }
  | { type: "error"; message: string };
```

### 7.2 Tool call 必须进入 UI

当前 `tool.call/tool.result` 主要被放进 event log。增加 durable ToolActivity 投影。

优先方案：使用已有 `messages(role='assistant', tool_calls)` 和 `messages(role='tool')`，通过 `tool_call_id` 关联，不新增表。

```typescript
function projectToolActivities(messages: Message[]): ToolActivity[] {
  const results = new Map(
    messages
      .filter((m) => m.role === "tool" && m.tool_call_id)
      .map((m) => [m.tool_call_id!, m]),
  );

  return messages.flatMap((message) =>
    (message.tool_calls ?? []).map((call) => ({
      id: call.id,
      task_id: message.task_id,
      name: call.name,
      args: call.args,
      result: results.get(call.id)?.content,
      status: results.has(call.id) ? "completed" : "running",
    })),
  );
}
```

如果发现工具调用的 started_at/duration 无法从 Message 推导，再新增 `tool_activities` 表；不要一开始就重复存储。

### 7.3 Activity Timeline

默认展示简洁状态：

```tsx
<ActivityRow
  icon={statusIcon(activity.status)}
  title={friendlyToolName(activity.name)}
  summary={activity.summary}
  duration={activity.durationMs}
  expandable={Boolean(activity.detail)}
/>
```

工具名称映射集中管理：

```typescript
const TOOL_PRESENTATION = {
  parse_paper: { title: "解析论文", category: "research" },
  compose_capabilities: { title: "组合论文能力", category: "planning" },
  plan_product: { title: "制定产品方案", category: "planning" },
  generate_nextjs_app: { title: "生成应用", category: "code" },
  verify_app: { title: "验证应用", category: "verification" },
  run_in_sandbox: { title: "启动预览", category: "runtime" },
} as const;
```

默认不把原始 JSON 倾倒给普通用户。展开后分为 Summary、Input、Output、Logs。

### 7.4 代码块体验

Message Markdown renderer 增加：

- syntax highlighting。
- Copy。
- Wrap toggle。
- 文件名标题。
- 如果引用 workspace path，提供“在工作台打开”。

```tsx
function CodeBlock({ language, code, filePath }: Props) {
  return (
    <div className="group overflow-hidden rounded-lg border">
      <div className="flex items-center justify-between bg-muted px-3 py-1.5 text-xs">
        <button onClick={() => filePath && openWorkspaceFile(filePath)}>
          {filePath ?? language ?? "code"}
        </button>
        <CopyButton value={code} />
      </div>
      <SyntaxHighlighter language={language}>{code}</SyntaxHighlighter>
    </div>
  );
}
```

### 7.5 Turn Header 状态

只对当前或异常 Task 显示状态：

```text
Working…
Queued · 2 ahead
Waiting for approval
Waiting for your answer
Stopped
Failed · Retry
```

已完成 Turn 不显示内部 phase/status 标签，避免界面噪音。

### 7.6 PR-3 Definition of Done

- Tool call、Step、Approval、Artifact 在正确 Turn 中显示。
- 展开详情能看到工具参数和结果，但默认界面简洁。
- 当前 Task 的状态、耗时和失败原因实时更新。
- Markdown 代码块可复制、可从文件路径打开工作台。

---

## 8. PR-4：Workbench、代码 diff、修改与验证闭环

### 8.1 拆分 PreviewPanel

目标文件结构：

```text
web/components/workbench/
├── Workbench.tsx
├── WorkbenchTabs.tsx
├── PreviewTab.tsx
├── CodeTab.tsx
├── ChangesTab.tsx
├── TestsTab.tsx
├── ArtifactsTab.tsx
├── LogsTab.tsx
├── FileTree.tsx
├── EditorTabs.tsx
├── RevisionDiff.tsx
└── WorkbenchEmptyState.tsx
```

将数据逻辑移到：

```text
web/lib/workbench/useWorkspace.ts
web/lib/workbench/useEditorTabs.ts
web/lib/workbench/usePreview.ts
```

### 8.2 Workbench 上下文打开

统一 action：

```typescript
openWorkbench({ tab: "code", filePath: "app/page.tsx", line: 42 });
openWorkbench({ tab: "changes", revisionId: "rev_x" });
openWorkbench({ tab: "tests", artifactId: "artifact_x" });
openWorkbench({ tab: "preview" });
```

事件规则：

```text
preview.ready              → open preview（用户未 pin closed 时）
file.changed               → peek changes
verification.failed        → open tests
用户点击文件路径            → open code
用户点击 artifact          → open artifacts
```

### 8.3 Workspace revision diff API

复用已有 revision，不新增 git 仓库。标准化 API：

```text
GET /api/apps/{app_id}/revisions
GET /api/apps/{app_id}/revisions/{revision_id}
GET /api/apps/{app_id}/revisions/{revision_id}/diff
POST /api/apps/{app_id}/revisions/{revision_id}/restore
```

Diff 响应：

```json
{
  "revision_id": "rev_x",
  "source": "generator",
  "summary": "Implement upload flow",
  "files": [
    {
      "path": "app/page.tsx",
      "status": "modified",
      "additions": 31,
      "deletions": 8,
      "patch": "@@ ..."
    }
  ]
}
```

Python diff 示例：

```python
from difflib import unified_diff

def make_unified_diff(path: str, before: str, after: str) -> str:
    return "".join(
        unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
```

### 8.4 乐观并发控制

当前编辑保存只有 content，可能覆盖 Agent 的新修改。写接口增加 revision precondition：

```typescript
await api.writeAppFile(appId, path, {
  content,
  base_revision_id: tab.baseRevisionId,
});
```

服务端：

```python
if req.base_revision_id != current_revision_id:
    raise HTTPException(
        status_code=409,
        detail={
            "code": "workspace_revision_conflict",
            "current_revision_id": current_revision_id,
        },
    )
```

前端收到 409 后显示：

```text
文件已被 Agent 更新
查看差异 | 使用我的版本 | 重新载入
```

### 8.5 保存后的增量验证

手动保存成功后：

1. 创建 `source=user` revision。
2. 发 `file.changed` 和 `artifact.updated`。
3. debounce 500ms 后运行最小检查：格式/TypeScript。
4. Checks 结果进入 Tests Tab。

不要每次按键都触发构建。

### 8.6 Change Set

暂不新增复杂表，可使用 revision + task_id 投影：

```typescript
interface ChangeSetSummary {
  revisionId: string;
  taskId?: string;
  source: "generator" | "repair" | "user";
  summary: string;
  fileCount: number;
  additions: number;
  deletions: number;
  verificationStatus?: "pending" | "passed" | "failed";
}
```

每个 Turn 中展示紧凑卡片：

```text
Changed 6 files · +214 −37
Build passed · Open changes
```

### 8.7 Preview

- 始终使用服务端 `preview_url`。
- iframe 错误和 sandbox 状态分离。
- 支持 Refresh、Restart、Open、Stop。
- 支持 desktop/tablet/mobile viewport。
- Preview 加载失败显示诊断和“打开 Logs”。
- 用户手动关闭 Workbench 后不被普通 file event 强制打开；只有明确点击或严重错误才覆盖。

### 8.8 PR-4 Definition of Done

- 从聊天中的文件路径能一键打开文件。
- Changes 展示真实 unified diff。
- 用户保存不会静默覆盖 Agent 新版本。
- 修改后能看到增量检查结果。
- revision restore 后文件树、编辑器、预览一致刷新。

---

## 9. PR-5：会话管理与文献管理

### 9.1 统一命名

代码内部保留 Run，用户界面统一称为“会话”或“项目”。Task 对用户称为“本轮工作”。避免同时显示 Run/Task/Thread。

### 9.2 会话侧栏

新增服务端查询参数：

```text
GET /api/runs?q=&status=&paper_id=&archived=&cursor=&limit=
```

返回 cursor pagination，避免一次加载全部历史会话。

排序规则：

```text
pinned desc
last_message_at desc
created_at desc
```

UI 分组：

```text
Pinned
Today
Previous 7 days
Older
Archived（独立入口）
```

状态只展示：

```text
working
queued
waiting for you
failed
preview ready
```

不展示 `active · init`。

### 9.3 产品内 Dialog

替换 `window.confirm/prompt`：

```text
RenameDialog
DeleteRunDialog
ArchiveDialog
WorkspaceConflictDialog
```

删除确认展示对象名称和影响，默认焦点不放在危险按钮。

### 9.4 文献数据迁移

在 `papers` 增加可选字段：

```sql
ALTER TABLE papers ADD COLUMN authors_json TEXT;
ALTER TABLE papers ADD COLUMN year INTEGER;
ALTER TABLE papers ADD COLUMN abstract TEXT;
ALTER TABLE papers ADD COLUMN page_count INTEGER;
ALTER TABLE papers ADD COLUMN parse_progress INTEGER NOT NULL DEFAULT 0;
ALTER TABLE papers ADD COLUMN parse_error TEXT;
ALTER TABLE papers ADD COLUMN content_hash TEXT;
ALTER TABLE papers ADD COLUMN updated_at TIMESTAMP;
```

标签与集合使用关联表：

```sql
CREATE TABLE IF NOT EXISTS paper_tags (
  paper_id TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  PRIMARY KEY (paper_id, tag)
);

CREATE TABLE IF NOT EXISTS paper_collections (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS paper_collection_items (
  collection_id TEXT NOT NULL REFERENCES paper_collections(id) ON DELETE CASCADE,
  paper_id TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
  PRIMARY KEY (collection_id, paper_id)
);
```

迁移必须幂等，并兼容已有数据库。

### 9.5 上传与去重

上传时流式计算 SHA-256：

```python
digest = hashlib.sha256()
while chunk := await file.read(1024 * 1024):
    digest.update(chunk)
    target.write(chunk)

existing = storage.get_paper_by_hash(digest.hexdigest())
if existing:
    return {"paper": existing, "duplicate": True}
```

限制：

- PDF MIME 与文件头同时校验。
- 设置最大文件大小。
- 文件名不作为磁盘路径真相源。
- 重名但内容不同允许保存为新版本或新 paper_id。

### 9.6 文献详情

页面结构：

```text
Header：标题、作者、年份、标签、创建项目
左栏：PDF viewer + 页码
右栏：Overview / Capability / Evidence / Projects
```

Evidence 点击后跳转 PDF 页：

```typescript
interface EvidenceAnchor {
  page: number;
  quote: string;
  field: string;
  section?: string;
  confidence?: number;
}
```

### 9.7 使用真实 run-paper 关系

新增：

```text
GET /api/library/{paper_id}/runs
```

查询 `run_papers` join `runs`，删除标题包含推断。

### 9.8 解析状态

上传后状态机：

```text
uploaded
extracting
parsing
parsed
failed
```

前端显示进度和 Retry。解析 Task 与产品生成 Task 可分开，但事件仍属于一个 Run 时必须具有 task_id。

### 9.9 创建项目

文献页主操作：

```text
Create project from this paper
```

一次调用完成：

1. create Run。
2. attach paper。
3. 跳转会话。
4. Composer 预填产品化建议，但不自动发送，除非用户明确选择“一键开始”。

### 9.10 PR-5 Definition of Done

- 74+ 会话列表仍流畅，支持服务端搜索和分页。
- 用户不再看到内部 `active/init` 状态。
- 文献可预览、搜索、打标签、归类、去重。
- Evidence 可跳转到对应 PDF 页面。
- Referenced Runs 来自数据库真实关系。

---

## 10. PR-6：Agent 产品化工作流重构

### 10.1 问题

当前 Orchestrator 主要依赖模型自由选择工具。即使 Resource Gate 正确，也无法稳定保证产品方向、生成策略和质量。

目标是：

```text
确定性工作流负责阶段、依赖、恢复和门禁
Agent/LLM 负责阶段内部的分析、生成和修复
```

### 10.2 新工作流状态

```python
class WorkflowStage(StrEnum):
    INGEST = "ingest"
    UNDERSTAND = "understand"
    OPPORTUNITY = "opportunity"
    SELECT = "select"
    SPECIFY = "specify"
    DESIGN = "design"
    GENERATE = "generate"
    VERIFY = "verify"
    ACCEPT = "accept"
    DELIVER = "deliver"


class WorkflowState(BaseModel):
    run_id: str
    task_id: str
    stage: WorkflowStage
    paper_ids: list[str] = []
    capability_contract_ids: list[str] = []
    candidate_set_id: str | None = None
    selected_candidate_id: str | None = None
    prd_id: str | None = None
    demo_contract_id: str | None = None
    design_id: str | None = None
    workspace_artifact_id: str | None = None
    verification_report_id: str | None = None
    retry_counts: dict[str, int] = {}
```

WorkflowState 持久化为 artifact 或独立表。短期建议使用 typed artifact，避免再建一套状态表。

### 10.3 Workflow Controller

```python
class ProductizationWorkflow:
    def __init__(self, services: WorkflowServices) -> None:
        self.services = services

    async def advance(self, state: WorkflowState) -> WorkflowState:
        match state.stage:
            case WorkflowStage.INGEST:
                return await self._ingest(state)
            case WorkflowStage.UNDERSTAND:
                return await self._understand(state)
            case WorkflowStage.OPPORTUNITY:
                return await self._generate_candidates(state)
            case WorkflowStage.SELECT:
                return await self._select_or_wait(state)
            case WorkflowStage.SPECIFY:
                return await self._specify(state)
            case WorkflowStage.DESIGN:
                return await self._design(state)
            case WorkflowStage.GENERATE:
                return await self._generate(state)
            case WorkflowStage.VERIFY:
                return await self._verify(state)
            case WorkflowStage.ACCEPT:
                return await self._accept(state)
            case WorkflowStage.DELIVER:
                return await self._deliver(state)
```

Orchestrator 负责识别用户意图：

```text
new productization
question about paper
follow-up workspace edit
verification/fix request
preview operation
```

一旦识别为 productization，则交给 Workflow Controller，不再让模型任意跳阶段。

### 10.4 Capability Contract V2

在当前抽取字段上增加产品化边界：

```python
class ImplementationLevel(StrEnum):
    DIRECT = "direct"
    REMOTE_API = "remote_api"
    LOCAL_LIGHTWEIGHT = "local_lightweight"
    HEAVY_EXTERNAL = "heavy_external"
    MOCK_ONLY = "mock_only"
    UNSUPPORTED = "unsupported"


class ProductizableCapability(BaseModel):
    id: str
    name: str
    description: str
    implementation_level: ImplementationLevel
    required_inputs: list[str]
    observable_outputs: list[str]
    dependencies: list[str]
    risks: list[str]
    evidence_ids: list[str]
    confidence: float


class CapabilityContractV2(BaseModel):
    paper_id: str
    capabilities: list[ProductizableCapability]
    non_productizable_claims: list[str]
    recommended_demo_boundaries: list[str]
```

### 10.5 产品候选与评分

```python
class CandidateScore(BaseModel):
    user_value: float
    paper_differentiation: float
    build_feasibility: float
    demo_completeness: float
    data_availability: float
    integration_risk: float


class ProductCandidate(BaseModel):
    id: str
    name: str
    target_user: str
    primary_job: str
    value_proposition: str
    core_capability_ids: list[str]
    happy_path: list[str]
    implementation_level: ImplementationLevel
    score: CandidateScore
    total_score: float
    tradeoffs: list[str]
```

总分使用代码计算，不让模型自己随意给总分：

```python
def calculate_candidate_score(score: CandidateScore) -> float:
    positive = (
        score.user_value * 0.25
        + score.paper_differentiation * 0.20
        + score.build_feasibility * 0.20
        + score.demo_completeness * 0.20
        + score.data_availability * 0.15
    )
    return round(max(0.0, positive - score.integration_risk * 0.20), 4)
```

如果用户没有指定方向：

- 高置信度且明显优胜时自动选择推荐候选，并解释。
- 候选接近或真实/mock 边界差异大时进入 `waiting_user`，展示 Candidate Cards。

### 10.6 Demo Contract

PRD 后必须生成 Demo Contract：

```python
class DemoStep(BaseModel):
    id: str
    route: str
    actor_action: str
    selector: str | None = None
    input_value: str | None = None
    expected_visual_state: str
    expected_data_state: str | None = None


class DemoContract(BaseModel):
    product_name: str
    opening_state: str
    seed_data: list[dict[str, Any]]
    happy_path: list[DemoStep]
    loading_states: list[str]
    empty_states: list[str]
    error_states: list[str]
    responsive_expectations: list[str]
    mock_disclosures: list[str]
```

生成器和浏览器验收都消费同一个 Demo Contract。

### 10.7 设计阶段

新增 `ProductDesignSpec`：

```python
class ScreenSpec(BaseModel):
    id: str
    route: str
    purpose: str
    primary_action: str
    sections: list[str]
    states: list[str]


class ProductDesignSpec(BaseModel):
    information_architecture: list[str]
    screens: list[ScreenSpec]
    component_map: dict[str, list[str]]
    data_entities: list[str]
    api_contracts: list[str]
    visual_direction: str
    accessibility_requirements: list[str]
```

该阶段只产出设计规格，不写代码。

### 10.8 垂直切片生成

WorkspacePlan 增加 slice：

```python
class GenerationSlice(BaseModel):
    id: str
    title: str
    goal: str
    files: list[str]
    acceptance_ids: list[str]
    depends_on: list[str] = []


class WorkspacePlanV2(BaseModel):
    files: list[PlannedFile]
    slices: list[GenerationSlice]
```

建议切片：

```text
slice_shell       应用壳、导航、主题、种子数据
slice_happy_path  主用户闭环
slice_capability  论文核心能力的真实/模拟实现
slice_states      loading/empty/error
slice_polish      响应式、无障碍、视觉细化
```

每个 slice：

```python
for slice_plan in plan.slices:
    batch = await generator.generate_slice(context, slice_plan)
    validate_planned_paths(batch, slice_plan)
    revision = promote_atomically(batch)
    check = await verifier.run_incremental(revision)
    if not check.ok:
        await repairer.repair_slice(slice_plan, check)
        check = await verifier.run_incremental(revision)
    if not check.ok:
        raise SliceGenerationFailed(slice_plan.id, check)
```

### 10.9 真实集成边界

生成产物的 Manifest 必须声明：

```json
{
  "integration_mode": "mock | remote_api | local_lightweight | external",
  "mock_capabilities": ["..."],
  "real_capabilities": ["..."],
  "required_env": ["..."],
  "known_limitations": ["..."]
}
```

禁止只在 `real-api.ts` 留 TODO 却向用户声称产品已完整实现。

默认目标建议定义为“高质量全栈原型”：

- Next.js 页面与交互真实可用。
- API route/server action 可运行。
- 本地数据持久化或明确 seed data。
- 论文核心能力按 Manifest 声明真实或模拟。
- 不要求自动下载超大模型，除非用户明确授权。

### 10.10 Follow-up 编辑路由

用户已有 workspace 时：

```text
解释问题                → inspect/read，只回复
小范围 UI/逻辑修改       → inspect → patch → incremental check
大功能修改              → update PRD/design → new generation slice
修复构建                → verify → targeted repair
重新开始产品方向         → 显式创建新 candidate/spec，不静默覆盖
```

不要重新解析已解析论文，除非：

- 文献内容变更。
- 用户要求重新解析。
- Capability Contract 版本迁移且缓存无效。

### 10.11 PR-6 Definition of Done

- 新产品化任务按固定阶段推进并可从任意阶段恢复。
- 用户可以看到候选方向、真实/mock 边界和选择依据。
- 生成器消费 PRD + Demo Contract + Design Spec。
- 每个 slice 独立生成、验证、修复和 revision。
- follow-up 编辑复用 workspace，不从零生成。

---

## 11. PR-7：验证、浏览器验收与质量评测

### 11.1 验证分层

```text
Layer 0  workspace policy / manifest
Layer 1  format / lint / typecheck
Layer 2  unit tests
Layer 3  production build
Layer 4  runtime health
Layer 5  Demo Contract browser acceptance
Layer 6  visual and product quality
Layer 7  paper fidelity
```

### 11.2 VerificationReport V3

```python
class QualityDimension(BaseModel):
    score: float
    passed: bool
    findings: list[str]


class VerificationReportV3(BaseModel):
    technical_ready: bool
    runtime_ready: bool
    product_ready: bool
    checks: list[CheckResult]
    acceptance_results: list[AcceptanceResult]
    dimensions: dict[str, QualityDimension]
    repair_attempts: int
    blocking_findings: list[str]
```

维度至少包括：

```text
paper_fidelity
feature_completeness
interaction_completeness
visual_coherence
responsive_quality
accessibility
error_state_quality
```

### 11.3 product_ready 规则

```python
report.product_ready = all(
    [
        report.technical_ready,
        report.runtime_ready,
        all(item.passed for item in report.acceptance_results if item.required),
        not report.blocking_findings,
        report.dimensions["paper_fidelity"].score >= 0.75,
        report.dimensions["feature_completeness"].score >= 0.80,
    ]
)
```

Visual score 可作为软门禁开始，但必须记录，不能完全忽略。

### 11.4 浏览器验收

从 Demo Contract 生成操作，不让模型自由探索替代确定性验收：

```python
for step in contract.happy_path:
    page.goto(base_url + step.route)
    if step.actor_action == "fill":
        page.locator(step.selector).fill(step.input_value or "")
    elif step.actor_action == "click":
        page.locator(step.selector).click()
    expect_visible_state(page, step.expected_visual_state)
```

失败保存：

- step id。
- 当前 URL。
- screenshot。
- DOM excerpt。
- console errors。
- network failures。

这些内容进入 Verification artifact 和 Workbench Tests Tab。

### 11.5 评测集

建立：

```text
evals/papers/
├── nlp/
├── vision/
├── recommendation/
├── medical/
├── data/
├── systems/
└── multi-paper/
```

每个 case：

```yaml
id: attention-product
paper: attention.pdf
request: Build a visual attention explainer for ML students
expected:
  capability_terms:
    - self-attention
    - multi-head attention
  forbidden_claims:
    - production translation model included
  required_product_behaviors:
    - input token editing
    - attention visualization
  max_duration_seconds: 900
```

### 11.6 指标

```text
parse evidence coverage
capability contract validity
candidate selection agreement
first build pass rate
repair success rate
browser acceptance pass rate
product_ready rate
median/p95 duration
input/output tokens
estimated cost
stream TTFT
SSE-to-render latency
```

### 11.7 测试分层

#### 每个 PR

- unit。
- integration。
- frontend component。
- mock Playwright。

#### 每日/nightly

- 至少 3 个真实模型 pipeline。
- 至少 1 个带真实 PDF 的完整生成与浏览器验收。
- 保留 artifact、截图、报告和费用。

#### 发布前

- 全部评测集。
- Docker sandbox。
- 断线重连。
- restart recovery。
- Windows/Linux 路径差异。

### 11.8 PR-7 Definition of Done

- full pipeline 测试真正执行所有阶段。
- 至少三个不同领域的真实论文能够生成并通过浏览器验收。
- Tests Tab 能展示每个失败步骤的截图、日志和修复状态。
- product_ready 有唯一计算来源。

---

## 12. PR-8：性能、可观测性与文档收口

### 12.1 前端性能

- Monaco 和 syntax highlighter 延迟加载。
- Sidebar 长列表虚拟化。
- Store 使用 selector，避免整个 ChatPanel 订阅全部 events。
- events 只保留 UI 所需窗口，完整历史从服务端分页读取。
- delta 仍使用 rAF batch。
- Artifact/Revision 数据按 Tab 懒加载。

### 12.2 后端性能

- SQLite 写入继续批处理。
- Event subscriber queue 设置上限并记录 drop metric。
- PDF map/reduce 设置并发上限。
- Generation slice 设置 token/file size budget。
- Sandbox 操作有明确超时和 cancellation。

### 12.3 可观测性

每个事件和日志携带：

```text
run_id
task_id
step_id（如有）
message_id（如有）
revision_id（如有）
```

关键 trace：

```text
message accepted
task queued
worker claimed
provider first token
message completed
tool started/completed
slice promoted
verification completed
preview ready
```

### 12.4 文档

必须更新：

- `README.md`：真实能力、运行方式、限制。
- `docs/architecture/realtime-protocol.md`：统一为 v2。
- `docs/architecture/frontend-workbench.md`：新 AppShell/Workbench。
- `docs/architecture/generation-pipeline.md`：Workflow Controller、Demo Contract、slices。
- `docs/06-backend-api.md`：新 message/task/revision API。
- `docs/07-data-model.md`：paper metadata、tags、collections。
- `docs/capability-matrix.md`：真实完成证据。

### 12.5 PR-8 Definition of Done

- 文档与实际接口版本一致。
- 没有“模块存在”等同于“production-ready”的清单。
- 能通过 run_id/task_id 定位一次完整执行。
- 性能指标可以被采集和比较。

---

## 13. 数据库迁移策略

当前项目使用 SQLite，应采用显式 schema version，而不是在运行时散落 `ALTER TABLE`。

建议：

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Python：

```python
MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "initial", migrate_initial),
    (2, "task_lifecycle", migrate_task_lifecycle),
    (3, "paper_metadata", migrate_paper_metadata),
]

def apply_migrations(conn: sqlite3.Connection) -> None:
    applied = {
        row[0]
        for row in conn.execute("SELECT version FROM schema_migrations")
    }
    for version, name, migrate in MIGRATIONS:
        if version in applied:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            migrate(conn)
            conn.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (version, name),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
```

要求：

- 老数据库原地升级。
- 新数据库从零创建后结构一致。
- 每个迁移可重复检测，不重复添加字段。
- 测试 legacy fixture 升级。
- 不删除用户数据。

---

## 14. 安全要求

1. PDF 上传限制大小、文件头和 MIME。
2. Browser upload 测试只能使用受控 fixture。
3. Workspace path 继续使用 SafeWorkspacePolicy。
4. Preview 默认隔离 origin，不把主应用凭证传入 iframe。
5. 生成应用不得自动获得 PaperForge 主进程环境变量。
6. 真实第三方 API 集成必须显式列出 required env 和网络权限。
7. 删除会话/文献使用明确确认并展示影响。
8. Agent 不可把 mock 能力描述为真实模型能力。

---

## 15. 可访问性与响应式

最低要求：

- 所有 icon-only button 有 aria-label 和 tooltip。
- Dialog focus trap、Esc 关闭、恢复触发元素焦点。
- Sidebar、Workbench tabs、Editor tabs 支持键盘。
- streaming 区域避免每个 token 都触发 screen reader；完成时再播报完整回复。
- 状态不能只依赖颜色。
- 触控目标至少 40×40。
- 320px、768px、1280px、1440px 验收。
- reduced motion。

ARIA streaming 建议：

```tsx
<div aria-live="off">{streamingContent}</div>
{completed && (
  <div className="sr-only" aria-live="polite">
    PaperForge response completed.
  </div>
)}
```

---

## 16. 推荐提交顺序

每项一个独立 PR，不把所有修改塞入一个超大提交。

```text
PR-0  test baseline and capability matrix
PR-1  realtime task/message reconciliation
PR-2  app shell, layout, composer, scroll
PR-3  conversation turn and activity timeline
PR-4  workbench diff/edit/verification loop
PR-5  session and paper library
PR-6  deterministic productization workflow
PR-7  real pipeline evals and quality gates
PR-8  performance, observability, docs
```

每个 PR：

1. 先写失败测试或复现测试。
2. 做最小实现。
3. 运行相关测试。
4. 运行完整前后端测试。
5. 浏览器真实走查。
6. 更新 capability matrix。
7. 提交证据，不只提交勾选框。

---

## 17. 总体验收清单

### 实时会话

- [ ] 新消息无需刷新即可看到回复。
- [ ] 首 token 延迟和连接状态可观察。
- [ ] 重连不重复、不丢失。
- [ ] 切会话不串流。
- [ ] Queue/Interrupt/Stop 正确作用于 Task。

### 前端体验

- [ ] Composer 固定在底部。
- [ ] 聊天区正确占满。
- [ ] 智能滚动不抢用户位置。
- [ ] Activity Timeline 清晰。
- [ ] Tool、Artifact、Approval 属于正确 Turn。
- [ ] Workbench 可拖拽、可记忆。

### 代码工作台

- [ ] 聊天文件路径一键打开。
- [ ] 展示真实 diff。
- [ ] 用户编辑有冲突保护。
- [ ] 保存后有增量验证。
- [ ] revision restore 完整刷新。

### 会话与文献

- [ ] 会话分页、搜索、归档、置顶。
- [ ] 不展示内部状态噪音。
- [ ] 文献 PDF 预览、元数据、标签、集合、去重。
- [ ] Evidence 跳转原文页。
- [ ] run-paper 真实关联。

### Agent/生成

- [ ] 确定性阶段与恢复。
- [ ] 候选评分与选择。
- [ ] Demo Contract 与 Design Spec。
- [ ] 垂直切片生成。
- [ ] 真实/mock 边界明确。
- [ ] follow-up 复用 workspace。

### 质量

- [ ] 真实 full pipeline。
- [ ] browser acceptance。
- [ ] paper fidelity gate。
- [ ] product_ready 单一来源。
- [ ] 真实模型 nightly eval。

---

## 18. 交给 Coding Agent 的完整提示词

下面的提示词可以直接复制。建议让 Coding Agent 先执行 PR-0 和 PR-1，验收通过后再继续，而不是一次性修改全部内容。

```text
你正在维护仓库：C:\Users\34217\Desktop\Study\Project\PaperForge

你的任务是严格按照以下实施规格逐阶段优化 PaperForge：
docs/plans/2026-08-14-deep-optimization-implementation-plan.md

总体目标：
1. 修复当前模型回复只有刷新页面后才出现的 P0 Bug。
2. 将前端重构为具有 ChatGPT 对话流和 Codex 工作台特征的成熟产品交互，但不要复制品牌资产。
3. 打通 Conversation、Task、Step、Tool、Approval、Artifact、Workspace、Revision、Verification 和 Preview。
4. 改进会话管理与文献管理。
5. 将论文产品化后端从“模型自由调用工具”升级为“确定性工作流骨架 + Agent 局部推理”。
6. 建立真实论文→产品→构建→预览→浏览器验收的端到端评测。

必须先阅读：
- README.md
- CLAUDE.md
- docs/plans/2026-08-14-deep-optimization-implementation-plan.md
- docs/architecture/realtime-protocol.md
- docs/architecture/frontend-workbench.md
- docs/architecture/generation-pipeline.md
- docs/contracts/run-events.md
- docs/contracts/api.md

执行规则：
- 不要推倒现有 FastAPI、SQLite、Next.js、Zustand、SSE、Generation V3 和 Workspace revision 架构。
- 保留用户已有修改；先检查 git status。
- 使用小步、可验证、可回滚的修改。
- 不要为了“未来扩展”创建没有当前用途的抽象。
- 每个阶段先增加失败测试/复现测试，再实现，再验证。
- 不要把 mock 单测通过当成真实端到端完成。
- 不要在没有证据时修改 Definition of Done 为完成。
- 不得将 mock 能力描述为真实能力。
- 所有影响用户可见状态的服务端事件必须先持久化再广播，并支持重放。
- Run 是持久会话，Task 是一轮工作；停止 Task 不得永久终止 Run。
- 不要静默吞掉异常、未知 task_id、revision conflict 或验证失败。

实施顺序必须遵循：

阶段 A（首先只做 PR-0 + PR-1）：
- 修复当前前端失败测试和 React act warning。
- Message + Task 原子创建。
- POST /messages 返回完整 message、task、event_cursor。
- 增加 task.created/task.updated/task.completed 等持久事件。
- 所有 Task 状态变化走统一 lifecycle service。
- Composer 使用响应对账 optimistic message，并 upsert Task。
- reducer 支持 Task 事件和乱序 message/task。
- delta buffer 保留 task_id。
- projectTurns 不得丢弃“带未知 task_id”的消息。
- SSE 暴露真实 connection state。
- 增加一个不 mock /state 的 Playwright 测试，证明发送消息后无需刷新即可看到回复。

阶段 A 验收前不要开始视觉重构。必须提供：
- 后端测试结果。
- 前端测试结果。
- Next build 结果。
- Playwright 实时发送测试结果。
- 手动浏览器验证：回复无需刷新。

阶段 B（PR-2 + PR-3）：
- 建立正确占满视口的 AppShell。
- Composer 固定在聊天底部。
- Sidebar/Conversation/Workbench 独立滚动。
- Workbench 可拖拽并记忆宽度。
- 使用底部 sentinel 实现智能滚动。
- 建立 Conversation Turn 和 Activity Timeline。
- Tool call/result、Step、Approval、Artifact 必须进入正确 Turn。
- 改善 Markdown/代码块、复制、打开 workspace file。
- 保证移动端、键盘和 reduced motion。

阶段 C（PR-4 + PR-5）：
- 拆分 Workbench 组件与 hooks。
- 实现真实 revision unified diff。
- 文件保存增加 base_revision_id 冲突保护。
- 保存后触发增量检查并展示结果。
- 改造会话搜索、分页、归档和用户可理解状态。
- 文献增加 PDF preview、元数据、标签、集合、去重、解析进度和 Evidence 页面跳转。
- Referenced Runs 必须查询 run_papers，不得通过标题推断。

阶段 D（PR-6）：
- 实现 ProductizationWorkflow 和持久 WorkflowState。
- 增加 CapabilityContractV2、ProductCandidate、DemoContract、ProductDesignSpec。
- 候选总分由代码计算。
- 生成按 vertical slices 执行，每个 slice 独立验证和修复。
- Manifest 明确 mock/real integration boundary。
- follow-up 编辑复用 workspace，不重新跑整条论文解析生成链。

阶段 E（PR-7 + PR-8）：
- 建立 VerificationReportV3 和唯一 product_ready 计算。
- 从 Demo Contract 执行确定性浏览器验收。
- 保存 screenshot、console、network 和 DOM 诊断。
- 建立多领域论文 eval fixtures。
- 增加真实模型 nightly pipeline。
- 优化性能、可观测性、文档和 capability matrix。

每个阶段交付格式：
1. 先说明当前证据和准备修改的最小范围。
2. 列出修改文件。
3. 实现代码。
4. 运行针对性测试。
5. 运行完整测试与 build。
6. 使用浏览器验证真实用户流程。
7. 报告仍未完成的项目和风险。

特别注意当前 P0 的准确根因：
- Composer optimistic user message 没有 task_id。
- POST /messages 返回 task_id，但前端没有 upsert 新 Task。
- message.started 带真实 task_id，但 store.tasks 中没有对应 Task。
- projectTurns 只遍历已知 Task，导致 assistant message 在实时阶段被遗漏。
- 刷新后 /state 返回 Task，所以消息才出现。

不要使用“发送后调用 refresh()”作为最终修复。必须完善实时实体和事件契约，并覆盖乱序与重连。

现在先执行阶段 A。阶段 A 全部验收通过后，汇报结果并继续阶段 B；如果遇到需要改变产品语义或数据库破坏性迁移的决定，停止并说明证据与选项。
```

---

## 19. 最后说明

实施过程中最容易出现的错误是：

1. 先重做视觉，实时主链仍然错误。
2. 为了让页面显示而在每个事件后重新请求 `/state`，掩盖领域状态缺失。
3. 重复创建一套 Task/Message/Tool 数据结构，导致 hydration 与 realtime 再次分叉。
4. 把更多 prompt 当成生成质量优化，却没有设计契约和真实评测。
5. 把 mock pipeline 命名为 E2E。
6. 一次性修改几十个文件，无法定位回归。

正确策略是：先让同一个 Task 在 API、DB、SSE、Store、Turn 和 UI 中具有唯一、一致、可恢复的身份，然后再围绕这条可靠主链改善体验和生成质量。

