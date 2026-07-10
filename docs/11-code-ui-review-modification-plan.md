# PaperForge 代码 + UI 二次审查与修改方案

> 审查对象：`https://github.com/Vincent-Wenhan/PaperForge` 当前 main 分支 + 用户提供的当前 Web UI 截图
> 审查方式：静态代码审查 + UI 视觉/交互审查
> 说明：当前执行环境无法 `git clone` GitHub 仓库，因此没有实际运行 `pytest`、`npm run build` 或 Docker sandbox。本方案只基于仓库公开代码与截图进行判断。

---

## 1. 总体结论

PaperForge 现在的方向基本正确，已经不再是"只有设计文档"的阶段。代码里已经有：

- Productize-first 的 README 定位
- FastAPI 后端
- SSE 事件流
- 自写 Orchestrator
- 5 个 sub-agent
- phase gate
- approval 机制
- artifacts 路由
- template-based Next.js generator
- real build verifier
- Docker sandbox
- 三栏 IDE 风 Web UI

但是，当前项目离"稳定可演示 MVP"还有明显距离。
最大问题不是架构方向，而是以下几类断点：

```text
1. UI 看起来能打开，但工作台感和 artifact 展示不够；
2. GitHub 仓库里 web/lib 目录缺失，但前端代码依赖它；
3. Orchestrator phase 只存在内存里，多轮消息会重置；
4. 单论文产品化 flow 与 plan_product schema 不匹配；
5. Backend approval 已有，但前端没有完整 approval 交互；
6. Verifier 和 Sandbox 的 npm install/build 职责重复；
7. Artifact 生成和前端展示链路还没有真正闭合；
8. E2E 测试还没有覆盖真实产品化闭环。
```

所以这次修改建议的核心是：

```text
不要重构大架构。
先把"上传论文/选择论文 → capability card → PRD → Next.js app → verify → preview → UI 展示 artifact"打通。
```

---

## 2. 已经做得比较好的地方

### 2.1 后端架构已经比较完整

当前 `api/main.py` 已经完成了比较完整的 app 初始化：

- 初始化 database
- 初始化 storage
- 初始化 event manager
- Docker 可用时启动 sandbox manager 和 monitor
- 注册 runs/messages/events/library/sandboxes/preview/files/settings/approvals/artifacts 等路由
- 提供 `/api/health`

这说明后端不再只是空壳，已经接近完整 API 骨架。

### 2.2 message 重复保存问题已修复

`messages.py` 现在明确写了：

```python
# API layer owns user message persistence; orchestrator must not duplicate it.
storage.add_message(run_id=run_id, role="user", content=req.content)
```

而 `Orchestrator.run()` 里也有注释：

```python
# API layer saves the user message; orchestrator must not duplicate it.
```

所以我之前担心的"用户消息重复保存"在当前代码里已经被修复。

### 2.3 Orchestrator 已经有 phase gate

当前 `orchestrator/loop.py` 中已经定义了：

```python
class RunPhase(str, Enum):
    INIT = "init"
    PARSED = "parsed"
    COMPOSED = "composed"
    PLANNED = "planned"
    GENERATED = "generated"
    VERIFIED = "verified"
    PREVIEW_READY = "preview_ready"
    DONE = "done"
    ERROR = "error"
```

并且有 `ALLOWED_TOOLS` 和 `PHASE_TRANSITIONS`。
这比完全自由的 `LLM -> tool -> LLM` loop 更安全。

### 2.4 Verifier 已经不是纯假检查

当前 `verifier.py` 已经调用：

```python
npm install --no-audit --no-fund
npm run build
```

这说明 Verifier 已经从"只看文件结构"升级成了真实 build check。
这是很重要的进步。

### 2.5 Preview proxy 已支持多 HTTP 方法

当前 `preview.py` 已经使用：

```python
@router.api_route(
    "/{sandbox_id}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
```

这比之前只代理 GET 更合理，可以支持 generated Next.js app 内部的 API route。

### 2.6 文件 API 已有安全限制

当前 `files.py` 已经有：

- 路径穿越检查
- `node_modules`、`.next`、`.git` 等路径屏蔽
- 文件后缀 allowlist
- 1MB 文件大小限制

这部分已经明显比早期版本安全。

### 2.7 NextjsGenerator 已改成 template-based

当前 `nextjs_generator.py` 明确采用：

```text
copy template scaffolding
→ LLM 只生成业务文件
→ 覆盖 app/page.tsx、lib/mock-api.ts、lib/real-api.ts
```

这是正确方向。
比让 LLM 从零生成完整 Next.js 工程稳定很多。

---

## 3. 当前最重要的问题

### P0-1：GitHub 仓库中缺少 `web/lib`，但前端依赖它

**问题确认：确实存在。**

`.gitignore` 里的 `lib/` 规则把 `web/lib/` 也一起 ignore 了，导致 `web/lib/api.ts` 和 `web/lib/store.ts` 虽然 local 存在，但从未被 commit/push 到 GitHub。

但前端代码大量依赖：

```typescript
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
```

如果有人 clone 仓库并 `npm run build`，会直接 Module not found。

**修复方式：**

```diff
- lib/
+ /lib/
```

把 `lib/` 改成 `/lib/`，表示只 ignore 仓库根目录的 `lib/`，不影响 `web/lib/`。同步地，把 `build/` / `dist/` / `parts/` / `sdist/` / `var/` / `wheels/` / `eggs/` / `.eggs/` / `downloads/` / `develop-eggs/` 都加 `/` 前缀，避免误伤其他子项目。

之后再 `git add web/lib/`，把 `api.ts` 和 `store.ts` 补进仓库。

**验收标准：**

```bash
git check-ignore -v web/lib/api.ts
# 应该没有输出，表示未被 ignore
```

---

### P0-2：Orchestrator phase 存在内存里，多轮对话会重置

**问题确认：确实存在。**

当前 `messages.py` 每次收到新消息都会创建一个新的 orchestrator：

```python
orchestrator = Orchestrator()
task_manager.start(run_id, orchestrator.run(...))
```

而 `Orchestrator` 的 phase 是实例变量：

```python
self.phase: RunPhase = RunPhase.INIT
```

这意味着每次用户发新消息，phase 都从 `INIT` 开始。

这会影响这些场景：

```text
1. 第一次：parse_paper 已经完成，phase 变为 PARSED；
2. 用户第二次补充需求："做成医学图像修复 demo"；
3. 新 Orchestrator 被创建，phase 又回到 INIT；
4. phase gate 只允许 parse_paper / finish；
5. plan_product / generate_nextjs_app 可能被拒绝。
```

**修复方式（方案 A：在 runs 表中加 phase 字段）：**

```sql
ALTER TABLE runs ADD COLUMN phase TEXT DEFAULT 'init';
```

Storage 层加：

```python
def update_run_phase(self, run_id: str, phase: str) -> None:
    now = datetime.utcnow().isoformat()
    with self._lock, self._conn() as conn:
        conn.execute(
            "UPDATE runs SET phase = ?, updated_at = ? WHERE id = ?",
            (phase, now, run_id),
        )

def get_run_phase(self, run_id: str) -> str:
    with self._conn() as conn:
        row = conn.execute(
            "SELECT phase FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        return row["phase"] if row else "init"
```

Orchestrator 初始化时：

```python
self.phase = RunPhase(self.storage.get_run_phase(run_id) or "init")
```

每次 tool 成功后：

```python
if call.name in PHASE_TRANSITIONS:
    self.phase = PHASE_TRANSITIONS[call.name]
    self.storage.update_run_phase(run_id, self.phase.value)
```

**验收标准：**

```text
第一轮 parse_paper 后 phase = parsed，DB 中 runs.phase = 'parsed'
第二轮 user message 后 phase 仍然 parsed
plan_product 能继续执行
```

---

### P0-3：单论文流程与 `plan_product` schema 不匹配

**问题确认：确实存在。**

当前 phase gate 允许：

```text
PARSED -> plan_product
```

但 tool definition 里 `plan_product` 的 required input 是：

```json
{
  "composition_id": "...",
  "user_requirement": "..."
}
```

单论文情况下，用户上传一个 PDF 后只有 capability card，没有 composition。
这会导致 LLM 即使想直接 plan，也没有合法的 `composition_id`。

**修复方式（让 `plan_product` 同时支持 `composition_id` 和 `card_ids`）：**

修改 tool schema：

```json
{
  "composition_id": {"type": "string"},
  "card_ids": {"type": "array", "items": {"type": "string"}},
  "user_requirement": {"type": "string"}
}
```

校验逻辑：

```python
if not composition_id and not card_ids:
    return error("Need either composition_id or card_ids")
```

**验收标准：**

```text
单论文 flow：
parse_paper -> plan_product(card_ids=[...]) -> generate -> verify -> preview

多论文 flow：
parse_paper x N -> compose_capabilities -> plan_product(composition_id=...) -> generate -> verify -> preview
```

---

### P0-4：Backend 已有 approval，但 UI 没有 approval 交互

**问题确认：确实存在。**

当前后端有：

- `DANGEROUS_TOOLS = {"generate_nextjs_app", "run_in_sandbox"}`
- `approval.requested` event
- `/api/approvals/{approval_id}/resolve` endpoint

但前端订阅事件时只处理：

```text
message.delta
tool.call
tool.result
artifact.created
sandbox.started
sandbox.error
preview.ready
run.started
run.finished
run.error
```

没有看到：

```text
approval.requested
approval.resolved
```

结果是：当 orchestrator 调用 `generate_nextjs_app` 或 `run_in_sandbox` 时，后端会等待用户 approval；但前端没有弹出按钮，用户无法 approve，最终 timeout。

这会直接卡住 demo。

**修复方式：**

1. 后端 `api/routes/approvals.py` 已经有 resolve endpoint，保持不变
2. 前端 `ChatPanel.tsx` 增加：

```typescript
sse.on("approval.requested", (data) => {
  addEvent({
    id: data.approval_id,
    type: "approval.requested",
    data,
    run_id: currentRun.id,
  });
  addPendingApproval(data);
});

sse.on("approval.resolved", (data) => {
  resolvePendingApproval(data.approval_id, data.approved);
});
```

3. 新增 `ApprovalCard` 组件：

```tsx
<ApprovalCard
  approvalId={event.data.approval_id}
  toolName={event.data.tool_name}
  args={event.data.args}
  onApprove={() => api.resolveApproval(approvalId, true)}
  onReject={() => api.resolveApproval(approvalId, false)}
/>
```

4. Store 里新增：

```typescript
pendingApprovals: Approval[]
addPendingApproval()
resolvePendingApproval()
```

**验收标准：**

```text
orchestrator 调用 generate_nextjs_app 时
前端弹出 ApprovalCard
用户点 Approve 后 tool 真正执行
用户点 Reject 后 tool 返回 rejected 错误
```

---

### P0-5：Verifier 和 Sandbox 都在 build，职责重复且执行环境不一致

**问题确认：部分存在。**

现在 Verifier 会在宿主机执行：

```text
npm install
npm run build
```

Sandbox 启动时又会在 Docker 容器里执行：

```text
npm install
npm run build
npm run dev
```

问题：

```text
1. 重复 install/build，速度慢
2. Verifier 在宿主机执行，不一定有 Node/npm
3. Sandbox 在 Docker 里执行，结果可能和宿主机不同
4. Build logs 分散，不利于前端展示
5. 如果 Verifier 成功但 Docker build 失败，用户会困惑
```

**修复方式（做一个统一的 `BuildRunner`，让 Verifier 和 Sandbox 共享）：**

新增 `paperforge/sandbox/build_runner.py`：

```python
class BuildRunner:
    async def install_and_build(
        self, app_path: Path, mode: Literal["docker", "local"]
    ) -> BuildResult:
        ...
```

推荐默认策略：

```text
Docker 可用：
  Verifier 使用 Docker build runner
  Sandbox 不重复 build，直接 npm run dev

Docker 不可用：
  Verifier 可以 local build，但必须标记 environment = local
  Sandbox 不默认 local dev，除非用户确认
```

最终职责：

```text
Verifier:
  install + build + logs + report

Sandbox:
  dev server + health check + preview URL

Build logs:
  保存为 artifact，Verification tab 展示
```

**验收标准：**

```text
verify_app 能真实产生 build_succeeded/build_errors
run_in_sandbox 后 iframe 能加载 preview
失败时 UI 明确显示原因
```

---

### P0-6：Artifact event 生成不完整，前端无法稳定展示过程

**问题确认：确实存在。**

当前 `handle_parse_paper` 会发 `artifact_created`，但 `handle_compose`、`handle_plan_product`、`handle_generate`、`handle_verify` 保存 artifact 后都没有发 `artifact.created`。

这会导致前端 timeline 不完整：

```text
可能看到 capability card created，
但看不到 composition / PRD / app / verification report created。
```

**修复方式：**

所有保存 artifact 的 handler 都应该统一：

```python
artifact_id = ctx.storage.save_artifact(...)
await ctx.emit.artifact_created(artifact_type, artifact_path, artifact_id)
```

需要修改的 handler：

```text
handle_compose
handle_plan_product
handle_generate
handle_verify
```

同时 `artifact.created` payload 应该包括：

```json
{
  "artifact_id": "...",
  "type": "prd",
  "title": "...",
  "summary": "...",
  "path": "...",
  "metadata": {}
}
```

前端收到后：

```typescript
addArtifact()
addEvent()
```

**验收标准：**

```text
parse_paper / compose / plan_product / generate / verify 都发 artifact.created
前端 timeline 能看到每个 artifact 的创建事件
```

---

### P0-7：当前 UI 缺少"产物感"和"流程感"

**问题确认：确实存在。**

从截图看，当前 UI 骨架是对的：

```text
左侧：Runs + Library
中间：Chat
右侧：Preview / Code / Console / Verification
```

但是现在的问题是：

```text
1. 中间大面积空白，只有欢迎语和普通 chat；
2. 右侧只显示 No sandbox running；
3. 用户不知道下一步该做什么；
4. Library paper 不能明显关联到当前 run；
5. 没有 capability card / PRD / verification report 的展示入口；
6. Recent Runs 全是 New Run，无法区分；
7. 没有 run status / phase / artifact count。
```

这会让 PaperForge 看起来像普通 chatbot，而不是"论文产品化工作台"。

**修复方式：**

#### 1. 中间 ChatPanel 加 EventTimeline

在 message 流里渲染 event cards：

```text
run.started
tool.call
tool.result
artifact.created
approval.requested
sandbox.started
preview.ready
run.finished
run.error
```

不要直接显示巨大 JSON。
默认显示摘要，展开后看 detail。

#### 2. 右侧增加 Artifacts tab

Tabs 改成：

```text
Preview | Artifacts | Code | Console | Verification
```

Artifacts 展示：

```text
Capability Card
Product Candidates
PRD
App Manifest
Verification Report
Build Logs
```

#### 3. Preview 空状态优化

现在的：

```text
No sandbox running
```

改成：

```text
No live preview yet

Current status:
✓ Paper uploaded
○ Capability card
○ PRD
○ App generated
○ Verification
○ Sandbox preview
```

#### 4. Sidebar 优化

Recent Runs：

```text
New Run
run_656d6d4b · active · 2 artifacts · 3 min ago
```

Library：

```text
med_agent
uploaded / parsed
has capability card
```

点击 library paper 后，设置 selected paper：

```text
Selected paper: med_agent
```

并在 chat input 上方显示 chip。

#### 5. RunHeader 优化

中间顶部显示：

```text
New Run    Active
run_656d6d4b · phase: parsed · 2 artifacts · no sandbox
```

**验收标准：**

```text
用户上传论文后
前端能看到 capability card 的 artifact card
前端能看到 PRD 的 artifact card
前端能看到 verification report 的 artifact card
用户点击 artifact card 能展开查看内容
```

---

## 4. P1：代码层建议

### P1-1：移除或收紧 orchestrator 的 read_file/write_file tools

**问题确认：部分存在。**

当前 `TOOL_DEFINITIONS` 里暴露了：

```text
read_file
write_file
```

虽然 phase gate 目前没有允许它们，但 tool 仍然在 definitions 中，LLM 可能尝试调用，然后被 phase gate 拒绝。

更干净做法：

```text
MVP 阶段从 TOOL_DEFINITIONS 中移除 read_file/write_file。
文件读写只由前端 CodeEditor 通过 Files API 完成。
```

如果保留，handler 不能允许 absolute path，必须限制在：

```text
DATA_DIR / generated_apps / app_xxx
```

当前 `handle_read_file` / `handle_write_file` 对 absolute path 没有 `relative_to(DATA_DIR)` 限制。
虽然现在 phase gate 不放行，但以后容易变成安全隐患。

---

### P1-2：Run status 需要更新

**问题确认：确实存在。**

当前 Orchestrator emits：

```text
run.started
run.finished
run.error
```

但 run 表里的 `status` 是否及时更新并不清楚。
UI sidebar 也没有显示 status。

建议：

```python
on run start:
  storage.update_run_status(run_id, "running")

on run finished:
  storage.update_run_status(run_id, "completed")

on run error:
  storage.update_run_status(run_id, "error")
```

同时加：

```python
storage.update_run_phase(run_id, phase)
```

前端 sidebar 和 header 直接显示。

---

### P1-3：Artifact list API 可以提供 include_data

**问题确认：确实存在（小问题）。**

当前 `list_artifacts` 返回 DB rows，通常只有：

```text
id / run_id / type / path / metadata / created_at
```

前端要展示内容时还得逐个 `GET /api/artifacts/{id}`。

可以增加：

```text
GET /api/artifacts?run_id=xxx&include_data=true
```

MVP 里 artifact 数量少，直接 include data 可以简化前端。

---

### P1-4：Library 上传需要防止文件名冲突

**问题确认：需要检查 `api/routes/library.py`。**

当前 `upload_paper` 使用：

```python
paper_id = Path(file.filename).stem
pdf_path = storage.library_dir / f"{paper_id}.pdf"
```

同名 PDF 会覆盖。
建议：

```python
paper_id = f"{slugify(stem)}_{uuid.uuid4().hex[:6]}"
```

或者如果同名存在，追加 suffix：

```text
attention
attention_2
attention_3
```

---

### P1-5：ConsoleLogs 当前是 polling，不是 SSE

当前 `ConsoleLogs.tsx` 每 3 秒 fetch 一次：

```typescript
fetch(`/api/sandboxes/${sandboxId}/logs`)
```

这可以接受。
但文档和早期设计里提过 logs SSE。
建议不要现在改，先保持 polling，等 preview 稳定后再做 SSE logs。

---

## 5. P2：产品化能力建议

### P2-1：CapabilityCard 加 evidence

PaperParser 输出应该支持：

```json
{
  "claim": "xxx",
  "evidence": {
    "section": "Method",
    "page": 4,
    "quote": "..."
  }
}
```

否则 Productize 时容易"看起来合理但不忠实论文"。

---

### P2-2：Composer 输出多个 product candidates

Composer 不应该只输出一个组合结果。
建议固定输出 2-3 个候选：

```text
Candidate A: Research workbench
Candidate B: Demo/product prototype
Candidate C: Real model integration tool
```

前端让用户选一个，再进入 PRD。

---

### P2-3：ProductPlanner needs_more_input 要接到 UI

后端 `plan_product` 已经支持：

```text
needs_more_input
questions
```

但 UI 要真正显示这些 questions，并让用户回答后继续。

前端可以渲染：

```tsx
<ClarificationCard questions={questions} />
```

---

## 6. P3：测试与 CI 建议

当前测试已经有：

- unit storage test
- integration API test
- e2e test_full_pipeline

但 `test_full_pipeline.py` 目前核心测试只是 `finish`，没有真正覆盖：

```text
parse_paper
plan_product
generate_nextjs_app
verify_app
artifact.created
```

### 必须增加的测试

#### 1. Orchestrator phase persistence test

```text
第一轮 parse_paper 后 phase = parsed
第二轮 user message 后 phase 仍然 parsed
plan_product 能继续执行
```

#### 2. Single-paper flow test

```text
parse_paper -> plan_product(card_ids=[...]) -> generate -> verify
```

#### 3. Approval flow test

```text
generate_nextjs_app 触发 approval.requested
resolve approval 后 task 继续
```

#### 4. Frontend build test

CI 里必须跑：

```bash
cd web
npm ci
npm run build
```

#### 5. Generated template build test

固定 template 应该单独测试：

```bash
cd paperforge/templates/nextjs_lightweight
npm install
npm run build
```

#### 6. Mock full pipeline test

用 mock LLM 返回固定 tool calls：

```text
parse_paper
plan_product
generate_nextjs_app
verify_app
finish
```

断言生成：

```text
capability_card artifact
prd artifact
nextjs_app artifact
verification_report artifact
```

---

## 7. 推荐修改优先级

### 第一轮：确保代码和 UI 能稳定启动

```text
1. 确认/提交 web/lib/*
2. npm run build 修到通过
3. pytest -q 修到通过
4. FastAPI /api/health 正常
```

验收标准：

```text
python -m uvicorn api.main:app --reload
cd web && npm run build
cd web && npm run dev
```

---

### 第二轮：修最小闭环的流程问题

```text
1. run.phase 持久化
2. 单论文 plan_product 支持 card_ids
3. approval.requested 前端弹卡片
4. all artifact handlers emit artifact.created
5. artifact tab 能读取 /api/artifacts
```

验收标准：

```text
上传/选择一篇论文
用户输入产品化需求
前端能看到 parse / plan / generate / verify 的事件卡片
危险步骤能 approve
```

---

### 第三轮：修 build/preview 可信度

```text
1. 抽象 BuildRunner
2. Verifier 使用 Docker build runner
3. Sandbox 不重复 build，只负责 dev preview
4. build logs 保存为 artifact
5. Verification tab 展示 build log / score / errors
```

验收标准：

```text
verify_app 能真实产生 build_succeeded/build_errors
run_in_sandbox 后 iframe 能加载 preview
失败时 UI 明确显示原因
```

---

### 第四轮：提升产品化体验

```text
1. EventTimeline
2. ArtifactPanel
3. ProductCandidateSelector
4. SelectedPaper chip
5. RunHeader status/phase/artifact count
6. Sidebar run/library metadata
```

验收标准：

```text
用户不看控制台也能理解：
系统现在在哪一步
生成了什么
为什么失败
下一步该点什么
```

---

## 8. 当前 UI 具体修改建议

基于截图，建议把当前 UI 改成下面的信息结构：

```text
┌─────────────────────────────────────────────────────────────┐
│ Sidebar │ Run Workspace                         │ Right Panel │
│         │ Header: run status / phase / artifacts│             │
│ Runs    │ Chat + Event Timeline                 │ Preview     │
│ Library │ User input + selected paper chip      │ Artifacts   │
│         │ Approval cards                        │ Code        │
│         │ Tool cards                            │ Console     │
│         │                                       │ Verification│
└─────────────────────────────────────────────────────────────┘
```

### Chat welcome 区增加 action cards

```text
Start from:
[Upload PDF]
[Use selected library paper]
[Generate product candidates]
[Open latest preview]
```

### Preview empty state

```text
No live preview yet

Current status:
✓ Paper uploaded
○ Capability card
○ PRD
○ App generated
○ Verification
○ Sandbox preview
```

### Artifact tab

展示：

```text
Capability Card
- Problem
- Method
- Inputs / Outputs
- Product Hints
- Constraints

PRD
- Product name
- Target users
- Must-have features
- Mock strategy

Verification
- Build status
- Coverage
- Boundary clear
- Recommendations
```

### Approval card

```text
PaperForge wants to run:
generate_nextjs_app

This will write files into:
data/generated_apps/app_xxx

[Approve] [Reject]
```

---

## 9. 一句话总结

PaperForge 当前不是"架构不对"，而是"闭环没完全呈现出来"。

最应该做的是：

```text
1. 补齐并提交 web/lib
2. 持久化 run phase
3. 支持 single-paper plan flow
4. 接上前端 approval
5. 所有 artifact 都发事件并展示
6. 统一 Verifier/Sandbox 的 build 逻辑
7. 把 UI 从普通聊天界面改成 artifact-first 工作台
```

这样 PaperForge 才会真正变成：

```text
论文产品化助手
而不是
一个能聊天、偶尔生成代码的 Web 壳子。
```
