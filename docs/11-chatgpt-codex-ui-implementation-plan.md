# PaperForge ChatGPT / Codex 风格 UI 与交互改造实施计划

> 审查范围：PaperForge `main` 分支当前前端、后端 API、Storage、Orchestrator、SSE、文件与 Artifact 相关代码，以及用户提供的当前运行截图。  
> 审查日期：2026-07-12  
> 目标：将 PaperForge 从“基础三栏调试界面”升级为接近 ChatGPT / Codex 使用体验的论文产品化工作台。

---

## 1. 结论摘要

当前 PaperForge 的三栏结构方向是合理的：

```text
左侧：会话与论文库
中间：对话与 Agent 过程
右侧：Preview / Artifacts / Code / Console / Verification
```

但目前的主要问题并不是视觉颜色，而是**产品状态模型、上下文传递和资源管理尚未支撑主流 Agent 产品的交互方式**。

当前截图中最典型的问题是：

```text
用户先问 “who are you”
→ Orchestrator 返回普通文本
→ run.phase 被设置为 done
→ 用户继续要求产品化论文
→ parse_paper 被 phase gate 拒绝
```

这与当前代码完全对应：

- `paperforge/orchestrator/loop.py` 在 LLM 没有继续调用 tool 时，直接把整个 run 设置为 `DONE / completed`。
- `ALLOWED_TOOLS[RunPhase.DONE] = set()`，因此后续消息不能再执行任何工具。
- UI 又根据 `phase=done` 静态显示“Capability card / PRD / App generated / Verified”全部完成，即使当前 run 实际上是 `0 artifacts`。

因此，本次改造必须按以下优先级进行：

1. **先分离“会话”和“产品化任务”的状态**。
2. **让论文通过显式附件上下文传入，而不是让 LLM 猜文件路径**。
3. **补齐会话、论文、生成文件、Artifact 的重命名、删除、归档和下载能力**。
4. **把 Chat 区改成“对话 + Agent Activity”，而不是输出原始 tool JSON**。
5. **把右侧改成真正的 Codex 风工作区：预览、文件、Artifact、日志、验证统一管理**。
6. 最后再统一视觉、动效、响应式和快捷键。

不建议先单独做“换成 ChatGPT 配色”。如果底层状态不改，UI 即使更漂亮，仍会出现截图中的流程错误。

---

## 1A. P0 专项：实时模型输出与真实状态同步

这一部分是本次追加审查中发现的最高优先级问题。当前现象是：

```text
用户发送消息
→ 后端模型实际在运行
→ 当前会话中看不到增量输出
→ 刷新页面后，最终回复才从数据库加载出来
```

右侧也存在同类问题：

```text
No live preview yet

Current status:
✓ Paper uploaded
✓ Capability card
✓ PRD
✓ App generated
✓ Verified
○ Done
```

这些勾选并不代表系统真的生成了对应产物，而是前端根据 `run.phase` 查询静态表后直接渲染出来的。

### 1A.1 代码级根因

#### 根因一：SSE 服务端与客户端的数据结构不一致

当前 `api/routes/events.py` 发出的 SSE 数据是一个 envelope：

```json
{
  "type": "message.delta",
  "data": {
    "text": "模型输出片段"
  },
  "run_id": "run_xxx"
}
```

但是 `web/lib/api.ts` 中的 `SSEClient` 会把整个 JSON 直接交给 handler：

```ts
const data = JSON.parse(e.data);
handler(data);
```

而 `web/components/ChatPanel.tsx` 按照已经解包的 payload 使用：

```ts
sse.on("message.delta", (data) => {
  addMessage({
    role: "assistant",
    content: data.text || "",
  });
});
```

因此这里的 `data.text` 实际是 `undefined`；真正内容在：

```ts
data.data.text
```

这个问题同时影响：

```text
message.delta
tool.call
tool.result
artifact.created
approval.requested
approval.resolved
sandbox.started
sandbox.error
preview.ready
run.started
run.finished
run.error
```

例如 `sandbox.started` 当前读取：

```ts
data.sandbox_id
```

但实际值在：

```ts
data.data.sandbox_id
```

这也是 Preview 可能一直显示 `No live preview yet` 的关键原因之一。

#### 根因二：每个 chunk 被当成一条新消息

`ChatPanel.tsx` 当前对每个 `message.delta` 调用一次 `addMessage()`。

即使修复 SSE 解包，模型每输出一个 chunk，前端也会创建一个新的 assistant 消息气泡，而不是在同一条回复中持续追加。

正确流程应当是：

```text
message.started
→ message.delta
→ message.delta
→ message.delta
→ message.completed
```

所有 delta 必须写入同一个 `message_id`。

#### 根因三：最终消息只在生成完成后持久化

`Orchestrator._stream_llm()` 会逐 chunk 调用：

```python
await emit.text(chunk.content)
```

说明后端 Provider 和 Orchestrator 已经具备流式输出路径。

但是完整 assistant message 是在模型结束后才调用：

```python
storage.add_message(...)
```

因此只要前端 SSE 没有正确消费，页面中就什么也看不到；刷新后 `listMessages()` 从 SQLite 读到最终消息，用户才看到结果。

#### 根因四：SSE 重连逻辑可能产生重复连接

浏览器原生 `EventSource` 已经自带自动重连。

当前 `SSEClient.onerror` 中又手动执行：

```ts
setTimeout(() => {
  if (this.es) this.connect(runId);
}, 1000);
```

这可能造成：

- 浏览器原生重连和手动重连同时发生。
- 多个 EventSource 并存。
- 同一事件重复消费。
- 多个定时器不断创建。

#### 根因五：历史 replay 与数据库消息可能重复

当前加载会话时同时：

1. 调用 `listMessages()` 加载数据库里的完整消息。
2. SSE endpoint 会 replay `EventManager` 内存中的全部历史事件。

如果历史中包括已完成回复的 `message.delta`，修复流式显示后，刷新或重连可能再次追加同一回复。

当前事件没有持久化的 `seq`，SSE 响应也没有发送标准 `id:`，所以无法实现可靠的断点续传与去重。

### 1A.2 推荐统一 SSE 协议

不要在不同组件中自行猜测数据结构。定义唯一的事件 envelope：

```ts
export interface RunEvent<T = unknown> {
  id: string;
  seq: number;
  run_id: string;
  task_id?: string;
  type: string;
  ts: number;
  payload: T;
}
```

SSE 示例：

```text
id: evt_000018
event: message.delta
data: {
  "id": "evt_000018",
  "seq": 18,
  "run_id": "run_x",
  "task_id": "task_x",
  "type": "message.delta",
  "ts": 1780000000,
  "payload": {
    "message_id": "msg_101",
    "delta": "Paper"
  }
}
```

`SSEClient` 统一解包：

```ts
private attach<T>(
  eventType: string,
  handler: (payload: T, event: RunEvent<T>) => void,
) {
  this.es?.addEventListener(eventType, (raw: MessageEvent) => {
    const event = JSON.parse(raw.data) as RunEvent<T>;
    handler(event.payload, event);
  });
}
```

不允许业务组件直接处理服务端原始 envelope。

### 1A.3 流式消息生命周期

新增事件：

```text
message.started
message.delta
message.completed
message.failed
```

Payload：

```json
{
  "message_id": "msg_101"
}
```

```json
{
  "message_id": "msg_101",
  "delta": "partial text"
}
```

```json
{
  "message_id": "msg_101",
  "content": "complete text"
}
```

后端推荐流程：

```python
message_id = storage.create_message(
    run_id=run_id,
    role="assistant",
    content="",
    status="streaming",
)

await emit.message_started(message_id)

async for chunk in llm.stream(...):
    buffer.append(chunk.content)
    await emit.message_delta(message_id, chunk.content)

storage.complete_message(
    message_id=message_id,
    content="".join(buffer),
)

await emit.message_completed(
    message_id=message_id,
    content="".join(buffer),
)
```

SQLite `messages` 建议增加：

```sql
status TEXT NOT NULL DEFAULT 'completed',
updated_at TIMESTAMP
```

可选优化：每 300–500 ms 或累计一定字符后 checkpoint 一次 partial content，这样刷新页面时也可以恢复尚未完成的回复。

### 1A.4 Zustand 必须支持更新消息，而不只是追加

当前 store 只有：

```ts
addMessage()
```

需要增加：

```ts
upsertMessage(message)
appendMessageDelta(messageId, delta)
completeMessage(messageId, content)
failMessage(messageId, error)
replaceMessages(messages)
```

示例：

```ts
appendMessageDelta: (messageId, delta) =>
  set((state) => ({
    messages: state.messages.map((message) =>
      message.id === messageId
        ? {
            ...message,
            content: message.content + delta,
            status: "streaming",
          }
        : message,
    ),
  }))
```

ChatPanel：

```ts
sse.on("message.started", ({ message_id }) => {
  upsertMessage({
    id: message_id,
    role: "assistant",
    content: "",
    status: "streaming",
  });
});

sse.on("message.delta", ({ message_id, delta }) => {
  appendMessageDelta(message_id, delta);
});

sse.on("message.completed", ({ message_id, content }) => {
  completeMessage(message_id, content);
});
```

### 1A.5 SSE 初始化与重连顺序

当前代码先：

```ts
sse.connect(runId)
```

再逐个：

```ts
sse.on(...)
```

虽然通常能够工作，但存在连接刚建立、历史事件已经开始 replay，而 handler 尚未全部挂载的竞争窗口。

建议：

```ts
const sse = new SSEClient();

registerAllHandlers(sse);
sse.connect(runId);
```

重连策略二选一：

#### MVP 推荐

依赖 EventSource 原生重连：

```ts
this.es.onerror = () => {
  this.connectionState = "reconnecting";
};
```

不要手动再次调用 `connect()`。

#### 完整方案

关闭原连接，并通过单一 timer 进行带退避的重连；必须防止多个 timer 和多个 EventSource 同时存在。

### 1A.6 事件持久化与断点续传

当前 `EventManager` 的 history 只在 Python 进程内存中：

```text
后端重启 → 事件历史消失
多进程部署 → 不同 worker 历史不一致
```

应使用之前计划中的 `run_events` 表，并给事件增加 `seq`：

```sql
CREATE TABLE run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    payload TEXT,
    created_at TIMESTAMP NOT NULL
);
```

SSE 支持：

```http
GET /api/runs/{run_id}/events?after_seq=18
```

或者读取浏览器发送的 `Last-Event-ID`。

前端初次加载推荐使用 snapshot + cursor：

```http
GET /api/runs/{run_id}/state
```

返回：

```json
{
  "run": {},
  "task": {},
  "messages": [],
  "artifacts": [],
  "sandbox": null,
  "pending_approvals": [],
  "event_cursor": 18
}
```

然后：

```http
GET /api/runs/{run_id}/events?after_seq=18
```

避免 `listMessages()` 和全量 SSE replay 互相重复。

### 1A.7 Artifact 实时更新目前也没有闭环

当前 `ChatPanel.tsx` 收到 `artifact.created` 时只执行：

```ts
addEvent(...)
```

没有：

- 调用 `addArtifact()`。
- 重新请求 artifact。
- 更新 Header 的 artifact count。
- 更新右侧 Artifacts tab。
- 更新 Preview checklist。
- 加载最新 Verification Report。

应改为：

```ts
sse.on("artifact.created", async ({ artifact_id }) => {
  const artifact = await api.getArtifact(artifact_id);
  addArtifact(artifact);
});
```

或者在使用 TanStack Query 后：

```ts
queryClient.invalidateQueries({
  queryKey: ["artifacts", runId],
});
```

### 1A.8 Run 状态和 Sidebar 当前不会实时更新

`runs/[id]/page.tsx` 只在页面加载时请求一次 run。

`ChatPanel.tsx` 收到：

```text
run.started
run.finished
run.error
```

时，只把它们追加到 events，不更新 `currentRun.status`、`currentRun.phase`，也不更新 Sidebar 中的 run。

需要新增明确事件：

```text
run.status.changed
task.phase.changed
```

并更新 Query Cache / Store：

```ts
sse.on("run.status.changed", ({ status }) => {
  updateCurrentRun({ status });
});

sse.on("task.phase.changed", ({ phase }) => {
  updateCurrentTask({ phase });
});
```

Orchestrator 每次成功 phase transition 时必须发出事件，而不是只更新 SQLite。

### 1A.9 右侧 Preview 显示假状态的根因

`PreviewPanel.tsx` 当前使用：

```ts
const PHASE_PROGRESS = {
  done: [
    "Paper uploaded",
    "Capability card",
    "PRD",
    "App generated",
    "Verified",
    "Done",
  ],
};
```

然后：

```ts
const progress = PHASE_PROGRESS[currentRun.phase]
```

这意味着只要 run 被错误设置成 `done`，前端就会显示：

```text
✓ Paper uploaded
✓ Capability card
✓ PRD
✓ App generated
✓ Verified
○ Done
```

即使 Header 同时显示：

```text
0 artifacts
```

这不是显示延迟，而是状态来源本身错误。

必须删除 `PHASE_PROGRESS` 作为事实来源。

### 1A.10 Preview 必须由真实数据推导

推荐建立 selector：

```ts
const capability = artifacts.find(
  (a) => a.type === "capability_card",
);

const prd = artifacts.find(
  (a) => a.type === "prd",
);

const app = artifacts.find(
  (a) => a.type === "nextjs_app",
);

const verification = artifacts.find(
  (a) => a.type === "verification_report",
);

const report =
  verification?.data?.report ??
  verification?.data;

const previewReady =
  sandbox?.status === "running" &&
  Boolean(sandbox?.id);
```

真实状态：

```ts
const progress = [
  {
    id: "paper",
    label: "Paper attached",
    status: attachedPapers.length > 0 ? "complete" : "pending",
  },
  {
    id: "capability",
    label: "Capability card",
    status: capability ? "complete" : "pending",
  },
  {
    id: "prd",
    label: "PRD",
    status: prd ? "complete" : "pending",
  },
  {
    id: "app",
    label: "App generated",
    status: app ? "complete" : "pending",
  },
  {
    id: "verified",
    label: "Build verified",
    status: report?.build_succeeded
      ? "complete"
      : verification
        ? "error"
        : "pending",
  },
  {
    id: "preview",
    label: "Live preview",
    status: previewReady ? "complete" : "pending",
  },
];
```

如果系统暂时还没有 `run_papers` 关系，则不要显示“Paper uploaded ✓”作为当前 run 的完成状态；Library 中存在 PDF 并不代表它已附加到当前会话。

### 1A.11 Sandbox 状态不能只依赖 SSE 瞬时事件

当前页面加载时没有恢复当前 run 已存在的 sandbox。

如果用户：

- 刷新页面。
- 临时断开 SSE。
- 在另一个标签页打开 run。
- 在 `sandbox.started` 发出后才进入页面。

那么 store 中 `sandbox` 仍然是 null，Preview 就显示 `No live preview yet`。

增加接口：

```http
GET /api/sandboxes?run_id={run_id}
```

返回该 run 最新 sandbox。

页面初始 hydration 时加载：

```ts
const sandbox = await api.getLatestSandboxForRun(runId);
setSandbox(sandbox);
```

事件处理：

```ts
sse.on("sandbox.started", (payload) => {
  setSandbox(payload);
});

sse.on("preview.ready", async ({ sandbox_id }) => {
  const sandbox = await api.getSandbox(sandbox_id);
  setSandbox(sandbox);
});

sse.on("sandbox.error", ({ sandbox_id, error }) => {
  updateSandbox({
    id: sandbox_id,
    status: "error",
    error,
  });
});
```

### 1A.12 Verification 页面目前不会自动读取报告

`PreviewPanel.tsx` 定义了：

```ts
const [report, setReport] = useState(null);
```

但当前代码没有从 artifacts 中设置 `report`。

应删除独立 report state，直接从 artifacts 计算最新报告：

```ts
const latestVerification = artifacts
  .filter((a) => a.type === "verification_report")
  .sort(sortByCreatedAtDesc)[0];

const report =
  latestVerification?.data?.report ??
  latestVerification?.data ??
  null;
```

这样 `artifact.created` 实时进入 store 后，Verification tab 也会立即更新。

### 1A.13 Console 也不是真正实时

`ConsoleLogs.tsx` 当前每 3 秒请求一次完整日志：

```ts
setInterval(loadLogs, 3000);
```

这不是阻塞 MVP 的 P0，但和 ChatGPT/Codex 风格的实时工作台不一致。

后续应改为：

```http
GET /api/sandboxes/{sandbox_id}/logs/stream
```

使用 SSE 推送增量日志，或者使用 cursor：

```http
GET /api/sandboxes/{sandbox_id}/logs?after=1024
```

避免每 3 秒重新下载全部日志。

### 1A.14 Composer 当前会静默取消正在运行的任务

`ChatPanel.tsx` 的 `sending` 只覆盖 `POST /messages` 的网络请求。

后端收到 POST 后立即返回 `queued`，所以 `sending` 很快变成 false；用户可以再次发送消息。

但 `RunTaskManager.start()` 会直接取消同一个 run 的旧 task：

```python
if existing and not existing.done():
    existing.cancel()
```

因此用户在生成过程中再发一条消息，会静默中断当前 Agent 任务。

需要：

- `run.started` 后设置 `isRunning=true`。
- `run.finished/run.error/run.cancelled` 后设置 false。
- 运行中发送按钮改为 Stop。
- Stop 调用 `/api/runs/{run_id}/cancel`。
- 新消息到来时，后端不能静默取消；应返回 409、排队，或要求用户显式停止旧任务。

### 1A.15 Pending Approval 也需要刷新恢复

Approval 目前主要依赖 SSE 事件加入 store。

如果用户在等待审批时刷新页面，前端需要调用：

```http
GET /api/approvals?run_id={run_id}
```

恢复 pending approvals，不能只依赖内存事件 history。

### 1A.16 推荐的前端初始化流程

当前 run 页面建议统一为：

```text
1. GET /api/runs/{id}/state
2. Hydrate run/messages/artifacts/sandbox/approvals
3. 记录 event_cursor
4. 注册全部 SSE handlers
5. connect SSE with after_seq=event_cursor
6. 后续只消费增量事件
```

如果暂时不实现 `/state` 聚合接口，则按以下顺序：

```text
Promise.all:
- getRun
- listMessages
- listArtifacts
- listApprovals
- getLatestSandboxForRun

完成 snapshot hydration
→ 注册 SSE handlers
→ connect SSE
```

不要让多个组件分别独立请求同一份状态。

### 1A.17 P0 修复顺序

建议分成四个提交：

#### Commit 1：修复 SSE payload contract

- 定义 `RunEvent`。
- 修复客户端 envelope 解包。
- handler 先注册、后 connect。
- 删除重复的手动 EventSource reconnect。
- 增加 SSE contract 测试。

#### Commit 2：修复流式消息合并

- 增加 message lifecycle events。
- Store 增加 append/update。
- 同一条 assistant message 实时增长。
- 完成后与数据库消息 reconcile。

#### Commit 3：修复实时资源状态

- `artifact.created` 实时更新 artifacts。
- `run/task phase` 实时更新。
- sandbox 初始恢复和事件更新。
- pending approval 初始恢复。
- latest verification report 自动加载。

#### Commit 4：移除假 Preview checklist

- 删除静态 `PHASE_PROGRESS`。
- 使用 artifacts、verification、sandbox 和 attached papers 推导。
- 增加 starting/building/error/ready empty states。
- Preview 和 Header 保持同一数据源。

### 1A.18 新增测试

#### 后端

```text
test_sse_event_envelope_contract
test_sse_event_has_id_and_seq
test_message_stream_started_delta_completed
test_phase_change_emits_event
test_artifact_created_emits_fetchable_artifact
test_latest_sandbox_by_run
test_pending_approval_survives_refresh
test_second_message_does_not_silently_cancel_active_task
```

#### 前端

```text
SSEClient unwraps payload
multiple deltas merge into one assistant message
completed message does not duplicate after snapshot refresh
artifact.created updates artifact panel immediately
task.phase.changed updates run header immediately
sandbox.started opens preview without refresh
verification artifact updates verification tab
reconnect does not duplicate old deltas
```

#### Playwright E2E

```text
1. Open a run.
2. Send “who are you”.
3. Confirm text appears token-by-token without refresh.
4. Attach a paper.
5. Start productization.
6. Confirm Agent Activity updates live.
7. Confirm capability artifact appears live.
8. Confirm PRD/App/Verification steps reflect real artifacts only.
9. Confirm preview automatically opens after sandbox is ready.
10. Refresh during a running task and verify state recovery.
11. Disconnect/reconnect SSE and verify no duplicate message chunks.
```

### 1A.19 实时链路验收标准

改造完成后必须满足：

1. 模型第一个文本 chunk 到达后，前端在 500 ms 内显示。
2. 同一回复只生成一个 assistant message。
3. 用户不刷新页面也能看到完整回复。
4. Artifact、Approval、Run status、Task phase、Sandbox 均实时更新。
5. Preview 不再根据 `phase=done` 伪造完成步骤。
6. 刷新页面后能够恢复当前消息、任务、审批、Artifact 和 Sandbox。
7. SSE 重连不重复消息和事件。
8. 正在运行的任务不会被下一条消息静默取消。


---

## 2. 本次代码审查确认到的当前实现

### 2.1 已有基础

当前仓库已经具备：

- Next.js App Router 前端。
- FastAPI 后端。
- Zustand 客户端状态。
- SSE 事件流。
- Monaco Editor。
- Docker sandbox preview。
- Artifact API。
- Run、Message、Paper、Sandbox、Artifact、Approval 的 SQLite 存储。
- Orchestrator phase gate 与 HITL approval。
- Preview 代理已支持 GET、POST、PUT、PATCH、DELETE、OPTIONS。
- 文件接口已有路径穿越、扩展名和大小限制。

因此本轮不需要推翻技术栈，也不需要重新换框架。

### 2.2 当前前端结构

当前主要组件为：

```text
web/components/
├── Sidebar.tsx
├── ChatPanel.tsx
├── MessageView.tsx
├── ToolCallCard.tsx
├── ApprovalCard.tsx
├── PreviewPanel.tsx
├── ArtifactCard.tsx
├── ConsoleLogs.tsx
└── VerificationReportView.tsx
```

已有页面骨架能工作，但每个组件目前仍偏 MVP：

- `Sidebar.tsx` 只能新建、切换 run 和上传 PDF。
- `ChatPanel.tsx` 负责消息、SSE、approval 和 event 展示，但绝大多数 event 只显示事件名。
- `MessageView.tsx` 仍是传统左右气泡布局。
- `PreviewPanel.tsx` 包含五个 tab，但 Preview 状态来自静态 `PHASE_PROGRESS`。
- Code 区只是扁平文件列表 + 单文件 Monaco。
- Artifact 只能展开查看，无重命名、删除、下载或版本管理。

### 2.3 当前 API 和 Storage 能力

目前：

- Run：创建、查询、删除、取消。
- Paper：上传、查询、删除、下载。
- Artifact：列表、详情。
- File：tree、read、write。
- Sandbox：启动、停止、状态、日志等。

目前缺少：

- Run rename / archive / restore / pin / duplicate。
- Paper rename / tags / attach-to-run。
- Artifact rename / delete / download / version。
- File create / rename / move / delete / download。
- 基于 app_id 的文件访问；当前文件接口依赖 sandbox_id。
- 持久化 task step / event timeline。
- 会话与一次产品化工作流的分离。

---

## 3. 最优先修复：会话状态与任务状态分离

## 3.1 当前问题

当前 `runs` 同时承担了两种含义：

```text
Run = 一段长期对话
Run = 一次 parse → plan → generate → verify 工作流
```

这两个概念不能合并。

ChatGPT 风格产品中，一段会话可以持续多轮；Codex 风格产品中，一段 thread 也可以继续追加任务。用户问一次“你是谁”，不应永久结束这段会话。

当前代码中，只要 LLM 返回普通文本且没有 tool call，就会：

```python
self.phase = RunPhase.DONE
storage.update_run_phase(run_id, "done")
storage.update_run_status(run_id, "completed")
```

这正是截图中后续 `parse_paper` 被拒绝的根因。

## 3.2 推荐数据模型

将 `runs` 定义为长期会话，再增加 `tasks`：

```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    title TEXT,
    goal TEXT,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP
);
```

状态职责：

```text
runs.status:
active / archived

tasks.status:
queued / running / waiting_approval / completed / error / cancelled

tasks.phase:
init / parsed / composed / planned / generated / verified / preview_ready
```

一次聊天可以没有 task，也可以先后产生多个 task。

例如：

```text
Run: “MedAgent 产品化”
├── 普通问答：“你是谁？”
├── Task 1：解析 MedAgent 并生成候选方案
├── 用户继续修改需求
└── Task 2：重新生成并验证 App
```

## 3.3 Orchestrator 修改规则

短期最小修复：

- 普通文本回复后，只把 run 状态改为 `active/idle`。
- 不要把 phase 自动改成 `done`。
- 只有显式调用 `finish`，或者任务达到明确终态时，才结束当前 task。
- 新的产品化意图到来时创建新的 task，phase 从 `init` 开始。
- phase gate 应读取 `task.phase`，而不是 `run.phase`。

长期推荐接口：

```python
async def run(
    run_id: str,
    task_id: str | None,
    user_message: str,
    attachments: list[AttachmentRef],
) -> None:
    ...
```

## 3.4 UI 修改

Run Header 不再显示：

```text
completed | phase: done | 0 artifacts
```

改为两层：

```text
MedAgent 产品化                       ···
Conversation active

Current task
Generating product plan · Step 3 of 6
```

无 task 时显示：

```text
Ready
Attach a paper or describe what you want to build.
```

## 3.5 验收标准

必须通过以下 E2E：

```text
1. 创建新会话。
2. 用户问 “who are you”。
3. 系统正常回答。
4. 用户选择论文并说“把它产品化”。
5. 同一个会话中 parse_paper 能正常执行。
6. 不出现 “not allowed in phase done”。
```

---

## 4. 论文上下文：从“猜路径”改成显式附件

## 4.1 当前问题

截图中用户点击或输入 `med_agent (1)` 后，LLM 构造：

```text
parse_paper({"pdf_path":"data/library/med_agent (1).pdf"})
```

这存在多个问题：

- 用户不应该知道服务器文件路径。
- 论文显示名、paper_id 和真实文件路径可能不同。
- 当前上传逻辑会 slugify 文件名，括号和空格可能被替换。
- LLM 猜路径容易出错。
- Library 项当前只是文本列表，不会真正绑定到消息上下文。

## 4.2 推荐交互

在 Composer 中显式附加论文：

```text
[＋]  [📄 med_agent_1 ×]  请把这篇论文产品化
```

用户可以：

- 点击左侧论文的“添加到当前会话”。
- 从 Composer 的附件菜单选择“从论文库添加”。
- 直接拖拽 PDF。
- 上传新 PDF 后自动选中。

## 4.3 API 修改

扩展消息请求：

```python
class MessageCreate(BaseModel):
    content: str
    paper_ids: list[str] = []
    artifact_ids: list[str] = []
    mode: str | None = None
```

请求示例：

```json
{
  "content": "把这篇论文产品化",
  "paper_ids": ["med_agent_1"],
  "mode": "productize"
}
```

Tool 改为优先接收 `paper_id`：

```json
{
  "name": "parse_paper",
  "input_schema": {
    "paper_id": "string"
  }
}
```

Tool handler 内部通过 Storage 获取真实路径：

```python
paper = storage.get_paper(paper_id)
pdf_path = paper["pdf_path"]
```

禁止 LLM 自己拼接 `data/library/...`。

## 4.4 数据关系

增加 run 与 paper 的关联：

```sql
CREATE TABLE run_papers (
    run_id TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    attached_at TIMESTAMP NOT NULL,
    PRIMARY KEY (run_id, paper_id)
);
```

## 4.5 验收标准

- 用户无需输入文件路径。
- 左侧点击论文即可附加。
- Composer 显示已附加论文 chip。
- 切换会话后，各会话保留自己的论文上下文。
- LLM tool call 中只出现 `paper_id`，不出现用户可见服务器路径。

---

## 5. 目标 UI 信息架构

## 5.1 整体布局

推荐保留三栏，但升级为可折叠、可拖拽的 App Shell：

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Global header / command palette / connection status                 │
├──────────────┬──────────────────────────────┬────────────────────────┤
│ Navigation   │ Conversation + Agent Activity│ Workbench              │
│              │                              │                        │
│ New task     │ Messages                     │ Preview                │
│ Search       │ Task timeline                │ Files                  │
│ Chats        │ Approval cards               │ Artifacts              │
│ Papers       │                              │ Logs                   │
│              │ Composer + attachments       │ Verification           │
└──────────────┴──────────────────────────────┴────────────────────────┘
```

建议宽度：

```text
Sidebar: 260px，可折叠到 56px
Conversation: 最小 420px
Workbench: 最小 480px
```

使用 `react-resizable-panels` 保存用户拖拽后的布局。

## 5.2 ChatGPT 与 Codex 风格的融合

ChatGPT 风格重点：

- 会话列表。
- 搜索、归档、删除、重命名。
- 简洁消息阅读体验。
- 底部悬浮 Composer。
- 附件作为上下文。
- 普通对话不受工作流状态限制。

Codex 风格重点：

- 项目/任务与文件并列。
- Agent 执行过程可查看但默认收起。
- 文件、代码、日志、验证结果在同一工作区。
- 预览和真实输出是核心，而不是只看聊天文本。
- 支持持续修改和重新验证。

不建议像素级复制某个产品，应学习其信息层级和操作习惯。

---

## 6. 左侧导航与会话管理

## 6.1 当前问题

`Sidebar.tsx` 当前：

- 所有会话大量显示为 `New Run`。
- 无当前选中态。
- 无时间分组。
- 无搜索。
- 无更多菜单。
- 无重命名、归档、删除。
- Library item 无点击和操作。
- 上传成功后使用 `window.location.reload()`，交互粗糙。

## 6.2 目标布局

```text
[＋ New task]
[⌕ Search]

TODAY
  MedAgent productization        ...
  Attention visualizer          ...

YESTERDAY
  New Run                        ...

PAPERS
  med_agent_1                    ...
  Attention Is All You Need      ...

[Settings]
```

会话按：

```text
Today / Yesterday / Previous 7 days / Older
```

分组。

## 6.3 Run Item 交互

每个 run hover 时出现 `···`：

```text
Rename
Pin / Unpin
Duplicate
Archive
Delete
```

操作建议：

- 单击：切换。
- 双击标题：inline rename。
- 右键：打开 context menu。
- Delete：必须确认。
- Archive：从主列表隐藏，但可搜索和恢复。
- 当前 run 使用明确背景与左侧 indicator。

## 6.4 后端 API

增加：

```http
PATCH /api/runs/{run_id}
{
  "title": "MedAgent productization",
  "pinned": true
}

POST /api/runs/{run_id}/archive
POST /api/runs/{run_id}/restore
POST /api/runs/{run_id}/duplicate
DELETE /api/runs/{run_id}

GET /api/runs?query=medagent&archived=false&limit=50
```

`runs` 表增加：

```sql
pinned INTEGER DEFAULT 0,
archived_at TIMESTAMP,
last_message_at TIMESTAMP
```

删除 run 时：

1. 取消活跃 task。
2. 停止相关 sandbox。
3. 删除或按策略保留生成目录。
4. 再删除数据库记录。

## 6.5 自动标题

不要长期保留 `New Run`。

在以下任一时机自动生成标题：

- 第一条有效用户消息后。
- 第一次附加论文后。
- Product Planner 产生 product name 后。

用户手动改名后，不再自动覆盖。

---

## 7. Chat 与 Composer 改造

## 7.1 消息视觉

当前 `MessageView.tsx` 将 assistant 放在灰色大气泡中，长文本可读性一般。

建议：

- 用户消息：右侧小型深色气泡。
- Assistant：无气泡或极浅背景，正文最大宽度约 720px。
- Markdown 标题、列表、代码块统一样式。
- 不把 tool JSON 直接当聊天消息。
- 错误信息转为可读卡片，而不是显示原始 JSON。

例如当前：

```json
{"ok": false, "tool": "parse_paper", "error": "..."}
```

应显示：

```text
Couldn’t start paper parsing

This task was already marked completed.
[Start a new productization task] [View details]
```

## 7.2 Streaming 修复

当前 `ChatPanel.tsx` 对每个 `message.delta` 都调用：

```ts
addMessage({ role: "assistant", content: data.text })
```

这会把流式 chunk 变成多条 assistant message。

改为：

```ts
startAssistantStream(messageId)
appendAssistantDelta(messageId, text)
finishAssistantStream(messageId)
```

Store 中按 message ID 合并内容。

## 7.3 Agent Activity

将 Tool Call、Tool Result、Artifact、Approval、Error 合并成一个任务活动卡：

```text
▾ Productizing MedAgent                           Running

✓ Read paper
✓ Extract capability card
● Create product candidates
○ Draft PRD
○ Generate app
○ Verify build
○ Start preview

2 tools used · 38s
```

默认只显示摘要，点击展开才显示：

- Tool 名称。
- 参数摘要。
- 运行时间。
- 输出 Artifact。
- 原始 JSON。
- 错误堆栈。

不要在 Chat 底部单独列出最近 20 个裸事件名。

## 7.4 Approval

Approval 应嵌入当前 task step：

```text
PaperForge wants to generate files

Target:
data/generated_apps/medagent-assistant

[Review plan] [Reject] [Approve]
```

批准后按钮变成静态状态，避免重复操作。

## 7.5 Composer

目标 Composer：

```text
┌───────────────────────────────────────────────────┐
│ [📄 med_agent_1 ×]                                │
│ Ask PaperForge to build or change something…      │
│                                                   │
│ ＋  Productize ▾             GLM-5.2 ▾   ■ / ↑    │
└───────────────────────────────────────────────────┘
```

支持：

- 多行输入。
- Enter 发送，Shift+Enter 换行。
- 上传 PDF。
- 从 Library 选择论文。
- 附加 Artifact。
- Send / Stop 切换。
- `Cmd/Ctrl + Enter` 发送。
- 当前 provider/model 只在需要时显示。
- 快捷动作：
  - Productize paper
  - Generate alternatives
  - Revise PRD
  - Fix build
  - Restart preview

API 已有 cancel endpoint，前端需要补 Stop 按钮调用它。

---

## 8. 右侧 Workbench 改造

## 8.1 Tab 结构

建议改为：

```text
Preview | Files | Artifacts | Logs | Verify
```

`Code` 改名为 `Files`，因为需要完整文件管理，而不只是编辑一个代码文件。

Tab 显示 badge：

```text
Files 18
Artifacts 4
Verify 2 issues
```

## 8.2 Preview

当前 Preview 空状态占据大面积空间，且静态 checklist 会被 `phase=done` 误导。

改造后状态必须来自真实资源：

```text
paper_attached       ← run_papers
capability_created   ← capability_card artifact
prd_created          ← prd artifact
app_generated        ← nextjs_app artifact
build_passed         ← verification report
preview_ready        ← running sandbox
```

不能只通过 `run.phase` 推断。

Preview toolbar：

```text
[←] [→] [Refresh]  /                [Desktop][Tablet][Mobile]
Sandbox: Running                    [Restart] [Open] [Stop]
```

功能：

- Refresh iframe。
- Open in new tab。
- Desktop / tablet / mobile viewport。
- Restart sandbox。
- Stop sandbox。
- 显示 starting / building / ready / error。
- Preview 失败时显示最后日志与重试按钮。

## 8.3 Files

当前文件树是扁平列表，API 仅支持 tree/read/write。

目标文件区：

```text
FILES
▼ app
    layout.tsx
    page.tsx
▼ components
    UploadPanel.tsx
▼ lib
    adapter.ts
package.json
```

支持：

- 文件夹折叠。
- 新建文件。
- 新建文件夹。
- 重命名。
- 移动。
- 删除。
- 下载单文件。
- 下载整个 app ZIP。
- 多标签页编辑。
- 未保存圆点。
- Ctrl/Cmd+S。
- 保存成功 toast。
- 离开未保存文件时提醒。
- 后期加入 diff。

## 8.4 文件 API

当前接口绑定 `sandbox_id`，导致未启动或已停止 sandbox 时难以管理 app 文件。

建议改为 app artifact 作为稳定资源：

```http
GET    /api/apps/{app_id}/tree
GET    /api/apps/{app_id}/files/{path}
PUT    /api/apps/{app_id}/files/{path}
POST   /api/apps/{app_id}/entries
PATCH  /api/apps/{app_id}/entries/{path}
DELETE /api/apps/{app_id}/entries/{path}
GET    /api/apps/{app_id}/download
```

请求示例：

```json
POST /api/apps/app_001/entries
{
  "type": "file",
  "path": "components/NewPanel.tsx",
  "content": ""
}
```

```json
PATCH /api/apps/app_001/entries/components/Old.tsx
{
  "new_path": "components/New.tsx"
}
```

所有操作继续复用当前 `_resolve_safe` 逻辑，并增加：

- 不允许操作 `node_modules`、`.next`、`.git`。
- Rename 后校验目标路径。
- Delete 文件夹需要显式确认。
- 写入采用临时文件 + atomic replace。
- 单文件上限保留 1 MB。

## 8.5 Artifacts

当前 Artifact API 和 UI 主要是只读查看。

增加操作：

```text
Open
Rename display name
Download JSON / Markdown
Delete
Use as chat context
Compare versions
```

Artifact 数据增加：

```sql
display_name TEXT,
version INTEGER DEFAULT 1,
updated_at TIMESTAMP,
parent_artifact_id TEXT
```

第一版可先实现：

- 打开。
- 删除。
- 下载。
- 添加为 Composer 上下文。

## 8.6 Verification

`PreviewPanel.tsx` 当前定义了 `report` state，但没有稳定地从 artifact 中选取最新 verification report。

应改为：

```ts
const latestReport = artifacts
  .filter(a => a.type === "verification_report")
  .sort(byCreatedAtDesc)[0]
```

Verification 页面展示：

- Build status。
- Build duration。
- Type/Lint errors。
- PRD must-have coverage。
- Mock/Real boundary。
- Security issues。
- 修复建议。
- `Ask PaperForge to fix` 按钮。

---

## 9. Library 文件管理

## 9.1 当前问题

当前 Library 后端支持上传、删除、下载，但前端 Sidebar 只展示文本，上传后直接刷新页面。

## 9.2 目标交互

Paper hover menu：

```text
Add to current chat
Open capability card
Rename
Download PDF
Delete
```

论文详情：

- 原始标题。
- 作者、年份。
- 上传时间。
- Parse 状态。
- Capability Card。
- 被哪些会话引用。
- Re-parse。

## 9.3 API

增加：

```http
PATCH /api/library/{paper_id}
{
  "title": "MedAgent"
}

POST /api/runs/{run_id}/papers/{paper_id}
DELETE /api/runs/{run_id}/papers/{paper_id}
```

注意：

- `paper_id` 是稳定标识，不应因重命名而改变。
- `title` 是可修改显示名。
- 删除论文时，如果仍被 run/task 引用，应提示或软删除。
- 上传完成后局部更新 query cache，不再 `window.location.reload()`。

---

## 10. 前端状态管理重构

## 10.1 当前问题

目前 Zustand 同时承担：

- UI 状态。
- 服务端 run/messages/artifacts。
- SSE 事件。
- sandbox。

这会导致：

- 切换 run 时大量手动清空。
- 缓存与重新请求难管理。
- 服务器状态与 UI 临时状态混合。
- 重命名、删除、归档后的列表同步复杂。

## 10.2 推荐分工

增加 TanStack Query：

```text
TanStack Query:
runs / papers / messages / artifacts / sandboxes / files

Zustand:
activeTab / panel sizes / selected files / open editor tabs /
composer attachments / sidebar collapsed / local preferences
```

建议 Query Keys：

```ts
["runs", filters]
["run", runId]
["messages", runId]
["artifacts", runId]
["papers"]
["paper", paperId]
["sandbox", runId]
["fileTree", appId]
```

SSE 到来后使用 query cache 更新，而不是把全部状态长期存进 Zustand。

## 10.3 SSE reducer

建立统一 reducer：

```ts
applyRunEvent(event) {
  switch (event.type) {
    case "message.delta":
    case "task.step.started":
    case "task.step.completed":
    case "artifact.created":
    case "approval.requested":
    case "sandbox.started":
    ...
  }
}
```

每个 event 必须含：

```json
{
  "id": "evt_x",
  "run_id": "run_x",
  "task_id": "task_x",
  "type": "task.step.completed",
  "seq": 18,
  "ts": 123456,
  "data": {}
}
```

使用 `id/seq` 去重。

---

## 11. 事件持久化与任务 Timeline

## 11.1 当前问题

`EventManager` 只将 history 保存在 Python 内存中：

```text
backend 重启 → timeline 消失
切换服务器进程 → timeline 不一致
```

Messages 虽然持久化，但 task step、preview、artifact 和 tool 状态没有完整持久化。

## 11.2 数据表

```sql
CREATE TABLE run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    data TEXT,
    created_at TIMESTAMP NOT NULL
);

CREATE INDEX idx_run_events
ON run_events(run_id, seq);
```

SSE 支持：

```http
GET /api/runs/{run_id}/events?after_seq=17
```

浏览器重连时从最后 seq 继续。

---

## 12. 视觉系统

## 12.1 当前问题

当前视觉主要依赖 Tailwind 基础类，没有形成统一 Design Token，交互组件也多为手写。

## 12.2 推荐新增依赖

```text
@tanstack/react-query
react-resizable-panels
@radix-ui/react-dropdown-menu
@radix-ui/react-dialog
@radix-ui/react-tooltip
@radix-ui/react-scroll-area
cmdk
sonner
```

也可以用 shadcn/ui 安装对应组件，但不要一次性引入完整模板。

## 12.3 Design Tokens

```css
:root {
  --sidebar: 240 5% 96%;
  --surface: 0 0% 100%;
  --surface-subtle: 240 5% 98%;
  --border-subtle: 240 6% 90%;
  --text-primary: 240 10% 10%;
  --text-secondary: 240 4% 46%;
  --accent: 240 5% 12%;
  --success: 142 70% 35%;
  --warning: 38 92% 45%;
  --danger: 0 72% 50%;
}
```

视觉原则：

- 减少大面积灰色聊天气泡。
- 使用细边框和轻微层级，不堆阴影。
- 状态色只用于真实状态。
- 统一 4/8/12/16/24 spacing。
- 支持深色模式，但放到核心交互完成之后。

---

## 13. 推荐组件结构

```text
web/
├── app/
│   ├── layout.tsx
│   └── runs/[id]/page.tsx
├── components/
│   ├── shell/
│   │   ├── AppShell.tsx
│   │   ├── ResizableWorkspace.tsx
│   │   └── GlobalHeader.tsx
│   ├── navigation/
│   │   ├── Sidebar.tsx
│   │   ├── RunList.tsx
│   │   ├── RunListItem.tsx
│   │   ├── PaperList.tsx
│   │   └── CommandPalette.tsx
│   ├── conversation/
│   │   ├── Conversation.tsx
│   │   ├── Message.tsx
│   │   ├── AgentActivity.tsx
│   │   ├── TaskStep.tsx
│   │   ├── ApprovalCard.tsx
│   │   └── Composer.tsx
│   ├── workbench/
│   │   ├── Workbench.tsx
│   │   ├── WorkbenchTabs.tsx
│   │   ├── preview/
│   │   ├── files/
│   │   ├── artifacts/
│   │   ├── logs/
│   │   └── verification/
│   └── dialogs/
│       ├── RenameDialog.tsx
│       ├── DeleteDialog.tsx
│       └── AttachPaperDialog.tsx
├── lib/
│   ├── api/
│   ├── queries/
│   ├── sse/
│   ├── stores/
│   └── types/
```

不要继续让 `ChatPanel.tsx` 和 `PreviewPanel.tsx` 承担越来越多职责。

---

## 14. 分阶段实施计划

## Phase 0：修复正确性、实时输出与真实状态

目标：先解决截图中的 phase 阻塞、必须刷新才能看到回复，以及 Preview 假状态问题。

任务：

1. 新增 task 模型，或至少停止普通回复自动把 run 设为 done。
2. Phase gate 迁移到 task。
3. 统一 SSE envelope，并修复前端 payload 解包。
4. 增加 `message.started/delta/completed`，同一回复按 message_id 合并。
5. 移除 EventSource 重复手动重连，增加 event id/seq 去重。
6. `artifact.created` 后实时更新 artifacts。
7. 新增 task phase/run status 事件并实时更新 Header、Sidebar。
8. 初始加载恢复 latest sandbox 和 pending approvals。
9. Preview 进度从 artifacts/verification/sandbox 推导，删除静态 `PHASE_PROGRESS`。
10. Verification tab 自动读取最新 verification artifact。
11. Message API 支持 `paper_ids`。
12. `parse_paper` 使用 paper_id，由后端解析路径。
13. 增加 E2E：普通问答后继续产品化、流式回复无需刷新、preview 自动出现。

验收：

- 同一会话能连续聊天和执行多个任务。
- 不再出现截图中的 phase done 错误。
- UI 不再显示不存在的 artifact 已完成。

## Phase 1：会话与论文管理

任务：

1. Run rename/archive/restore/delete/pin API。
2. Paper rename/delete/download/attach API。
3. Sidebar 时间分组、搜索、active state。
4. Hover `···` 菜单。
5. Composer 论文 chips。
6. 去掉 `window.location.reload()`。

验收：

- 会话和论文均可重命名、删除。
- 删除有确认。
- 会话可归档和恢复。
- 论文可直接附加到当前对话。

## Phase 2：Chat 与 Agent Activity

任务：

1. 流式文本按同一 message 合并。
2. 重写 Message 样式。
3. Agent Activity 时间线。
4. Tool result 默认摘要、详情折叠。
5. Approval 嵌入步骤。
6. Composer 多行、附件、Stop。
7. Run title 自动生成。

验收：

- 聊天区不再堆 raw JSON。
- 用户能清楚知道当前 agent 做到哪一步。
- 可取消正在执行的 task。

## Phase 3：Workbench、文件与 Preview

任务：

1. 可拖拽三栏。
2. Preview toolbar。
3. Files 嵌套树。
4. 新建、重命名、移动、删除文件。
5. Editor tabs、dirty state、Ctrl+S。
6. 下载 app ZIP。
7. Sandbox restart/stop/open。
8. Preview 状态和错误恢复。

验收：

- 文件管理无需启动 sandbox。
- 用户能编辑、重命名和删除生成文件。
- Preview 能刷新、重启和打开新页。

## Phase 4：Artifacts 与 Verification

任务：

1. Artifact rename/delete/download/context。
2. 版本信息。
3. Verification 自动读取最新 report。
4. Build errors 可跳转相关文件。
5. “Ask PaperForge to fix” 快捷动作。

验收：

- 用户能明确看到每个产物及其来源。
- 验证失败后可一键发起修复。

## Phase 5：视觉、快捷键与响应式

任务：

1. Design tokens。
2. Light/dark mode。
3. Command palette。
4. Keyboard shortcuts。
5. Tablet/mobile 布局。
6. Accessibility。
7. Skeleton、toast、empty/error states。

---

## 15. 测试计划

## 15.1 后端

```text
test_run_rename_archive_restore_delete
test_paper_rename_attach_detach_delete
test_message_with_paper_ids
test_plain_chat_does_not_finish_task
test_new_task_after_completed_task
test_file_create_rename_delete
test_artifact_download_delete
test_event_resume_after_seq
```

## 15.2 前端组件

```text
RunListItem context menu
Composer attachment chips
Streaming message merge
Task timeline state
File rename/delete confirmation
Preview status toolbar
Artifact actions
```

## 15.3 Playwright E2E

最关键场景：

```text
1. Create run
2. Ask “who are you”
3. Attach MedAgent paper
4. Ask to productize it
5. Parse succeeds
6. Approve generation
7. App is generated
8. Verification appears
9. Preview opens
10. Rename one generated file
11. Refresh preview
12. Rename and archive the conversation
```

---

## 16. MVP 范围建议

第一轮必须完成：

- 会话与 task 分离。
- 论文显式附件。
- Run rename/delete/archive。
- Paper rename/delete/attach。
- Agent Activity。
- Preview 正确状态。
- 文件 rename/delete/create。
- Preview restart/open。
- Streaming 合并。
- E2E 闭环。

可以后置：

- 多人协作。
- Git worktree。
- Artifact 复杂版本对比。
- 完整 diff review。
- 全局全文搜索。
- 移动端完整代码编辑。
- 高级自动化任务。

---

## 17. 最终验收标准

改造完成后，PaperForge 应达到：

1. 用户可以像 ChatGPT 一样管理长期会话。
2. 一段会话可以包含普通问答和多个产品化任务。
3. 用户不用输入服务器路径即可选择论文。
4. Agent 过程以清晰的 activity 展示，不暴露杂乱 JSON。
5. 生成的文件可以查看、新建、修改、重命名、移动、删除和下载。
6. Preview 可以刷新、重启、停止、打开新页和切换 viewport。
7. Artifact 可以查看、下载、删除并重新加入对话上下文。
8. 状态由真实 task/artifact/sandbox 数据驱动，不由静态 phase checklist 伪造。
9. SSE 断线重连后能够恢复任务状态。
10. 核心流程有自动化 E2E 测试。
11. 模型回复能够在同一条消息中实时流式增长，无需刷新。
12. Run、Task、Artifact、Approval、Sandbox 与 Verification 状态均能实时同步。
13. Preview checklist 只反映真实产物和执行结果，不再由静态 phase 伪造。
14. SSE 重连或页面刷新后不会重复历史 chunk，并能恢复当前执行状态。

---

## 18. 审查依据

本计划基于以下当前代码文件：

- `web/components/Sidebar.tsx`
- `web/components/ChatPanel.tsx`
- `web/components/MessageView.tsx`
- `web/components/ToolCallCard.tsx`
- `web/components/PreviewPanel.tsx`
- `web/components/ArtifactCard.tsx`
- `web/components/VerificationReportView.tsx`
- `web/lib/api.ts`
- `web/lib/store.ts`
- `web/package.json`
- `api/routes/runs.py`
- `api/routes/messages.py`
- `api/routes/library.py`
- `api/routes/files.py`
- `api/routes/artifacts.py`
- `api/routes/preview.py`
- `paperforge/storage/db.py`
- `paperforge/orchestrator/loop.py`
- `paperforge/orchestrator/events.py`

参考产品交互原则：

- ChatGPT Projects：对话、文件和项目上下文组合。
- ChatGPT 会话管理：归档与删除。
- Codex App：项目、长任务、文件和真实产物集中在同一工作区。
- Codex 长任务：计划、修改、执行、观察、修复的循环。

说明：本环境未直接启动该仓库；结论来自当前 GitHub `main` 分支代码逐文件审查和用户提供的实际运行截图。因此文档区分了“代码中已实现的能力”和“需要新增的能力”，没有把尚未验证的运行行为当成已完成事实。
