# PaperForge 代码审查与修改方案

> 审查对象：`https://github.com/Vincent-Wenhan/PaperForge`  
> 审查方式：静态阅读 GitHub 仓库代码、README、关键后端/前端/agent/sandbox 文件。当前执行环境无法解析 `github.com`，因此没有成功 `git clone` 并本地启动项目；以下结论基于仓库代码结构和关键文件内容判断。

---

## 1. 总体结论

PaperForge 当前方向是正确的，已经比旧 PaperPilot 更聚焦：

```text
Productize-first
PDF → Capability Card → Product Plan / PRD → Next.js App → Sandbox Preview
```

目前仓库已经具备以下基础：

- Python 包结构已经按 `agents / orchestrator / llm / sandbox / schemas / storage` 拆分。
- 后端使用 FastAPI，已经有 runs、messages、events、library、sandboxes、preview、files、settings、approvals 等路由。
- Orchestrator 已经实现了 `LLM → tool → LLM` 的基础 agentic loop，并且对 `generate_nextjs_app`、`run_in_sandbox` 增加了 approval 机制。
- Sub-agents 已经按 5 个角色拆分：`PaperParser / Composer / ProductPlanner / NextjsGenerator / Verifier`。
- Docker sandbox 已经有 node 容器、动态端口、资源限制、最大并发限制等基础能力。
- 前端已经采用 Next.js App Router + IDE 风格布局思路，包含 Chat、Preview、Code、Console、Verification 等模块雏形。

但是，当前项目还不是一个稳定 MVP。主要问题集中在：

```text
1. 前端可能无法 build。
2. Orchestrator 还是偏自由循环，缺少 phase gate。
3. API 层和 Orchestrator 存在用户消息重复保存。
4. Verifier 没有真正执行 npm build，验证可信度不足。
5. NextjsGenerator 仍然是从零生成文件，不够稳定。
6. Sandbox 直接 npm install + npm run dev，缺少 build-first 验证。
7. Preview proxy 只支持 GET，对 API route / POST demo 不够。
8. 文件读写接口安全边界还需要进一步收紧。
9. 前端缺 artifact timeline / product candidate selection，产品化过程展示不够强。
```

一句话判断：

```text
架构方向基本对，但最小闭环还不够硬，下一步应该优先修 P0/P1，先让 mock flow 和 generated app build flow 稳定跑通。
```

---

## 2. 当前项目是否符合预期目标

### 2.1 符合的部分

| 目标 | 当前状态 | 评价 |
|---|---|---|
| Productize-first | README 和目录结构都围绕论文产品化 | 符合 |
| 5 个 sub-agent | 已有 `paper_parser.py / composer.py / product_planner.py / nextjs_generator.py / verifier.py` | 符合 |
| 自写 Orchestrator | 已有 `paperforge/orchestrator/loop.py` | 符合，但需要约束 |
| 多 provider LLM | 已有 `llm/` 抽象层 | 基础可用 |
| FastAPI + SSE | 已有 events route 和 EventManager | 基础可用 |
| Docker sandbox | 已有 DockerSandboxManager | 基础可用 |
| Web 工作台 | 已有 Next.js app 和 PreviewPanel | 基础雏形 |
| Human-in-the-loop | dangerous tools 需要 approval | 符合 |

### 2.2 不符合或未完成的部分

| 目标 | 当前问题 | 影响 |
|---|---|---|
| 前端可启动 | `web/lib` 目录缺失，但页面 import `@/lib/api` / `@/lib/store` | 前端可能直接编译失败 |
| 可控流程 | Orchestrator 完全依赖 LLM tool calls，无 phase gate | 容易跳步、乱调用、无法稳定复现流程 |
| 真实验证 | Verifier 目前主要检查文件结构，不是真正 build | 生成 app 可能“报告成功但实际跑不起来” |
| Live preview 可信 | Sandbox 直接 `npm install && npm run dev` | dev 能启动不代表 build 通过 |
| Full-stack app 支持 | Preview proxy 只支持 GET | POST / API route / form submit 可能失败 |
| 产品化交互 | 缺 product candidates selection / artifact timeline | 不能体现 PaperForge 的核心差异化 |

---

## 3. P0：必须先修的问题

### P0-1：补齐前端 `web/lib`，保证 Next.js 能 build

#### 问题

`web/app/page.tsx` 使用：

```ts
import { api } from "@/lib/api";
```

`web/app/runs/[id]/page.tsx` 和 `PreviewPanel.tsx` 也依赖 `@/lib/api`、`@/lib/store` 等模块，但当前 `web/` 目录树没有 `lib/` 目录。

#### 影响

前端大概率直接报错：

```text
Module not found: Can't resolve '@/lib/api'
Module not found: Can't resolve '@/lib/store'
```

#### 修改方案

新增：

```text
web/lib/
  api.ts
  store.ts
  types.ts
  sse.ts
  utils.ts
```

建议最小实现：

```ts
// web/lib/types.ts
export type Run = {
  id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id?: string;
  role: "user" | "assistant" | "tool";
  content: string;
  created_at?: string;
  tool_calls?: any[];
};

export type Sandbox = {
  id: string;
  run_id: string;
  status: string;
  preview_url?: string;
  preview_port?: number;
  app_path?: string;
};

export type Artifact = {
  id: string;
  run_id: string;
  type: string;
  data?: any;
  metadata?: any;
  created_at?: string;
};
```

```ts
// web/lib/api.ts
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json();
}

export const api = {
  listRuns: () => request<any[]>("/runs"),
  createRun: (title?: string) =>
    request<any>("/runs", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  getRun: (id: string) => request<any>(`/runs/${id}`),
  listMessages: (runId: string) => request<any[]>(`/runs/${runId}/messages`),
  sendMessage: (runId: string, content: string) =>
    request<any>(`/runs/${runId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  listLibrary: () => request<{ papers: any[] }>("/library"),
  getFileTree: (sandboxId: string) => request<any>(`/files/sandboxes/${sandboxId}/tree`),
  readFile: async (sandboxId: string, path: string) => {
    const res = await fetch(`${API_BASE}/files/sandboxes/${sandboxId}/files/${path}`);
    if (!res.ok) throw new Error(await res.text());
    const json = await res.json();
    return json.content as string;
  },
  updateFile: (sandboxId: string, path: string, content: string) =>
    request<any>(`/files/sandboxes/${sandboxId}/files/${path}`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
};
```

```ts
// web/lib/store.ts
import { create } from "zustand";
import type { Run, Message, Sandbox, Artifact } from "./types";

interface AppState {
  currentRun: Run | null;
  messages: Message[];
  events: any[];
  sandbox: Sandbox | null;
  artifacts: Artifact[];
  activeTab: "preview" | "code" | "console" | "verification";
  setCurrentRun: (run: Run | null) => void;
  setMessages: (messages: Message[]) => void;
  addMessage: (msg: Message) => void;
  addEvent: (event: any) => void;
  setSandbox: (sb: Sandbox | null) => void;
  setArtifacts: (artifacts: Artifact[]) => void;
  setActiveTab: (tab: AppState["activeTab"]) => void;
}

export const useAppStore = create<AppState>((set) => ({
  currentRun: null,
  messages: [],
  events: [],
  sandbox: null,
  artifacts: [],
  activeTab: "preview",
  setCurrentRun: (run) => set({ currentRun: run }),
  setMessages: (messages) => set({ messages }),
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  addEvent: (event) => set((s) => ({ events: [...s.events, event] })),
  setSandbox: (sandbox) => set({ sandbox }),
  setArtifacts: (artifacts) => set({ artifacts }),
  setActiveTab: (activeTab) => set({ activeTab }),
}));
```

#### 验收标准

```bash
cd web
npm install
npm run build
```

必须通过。

---

### P0-2：修复用户消息重复保存

#### 问题

`POST /api/runs/{id}/messages` 已经保存了一次 user message，然后 `Orchestrator.run()` 内部又保存了一次同样的 user message。

#### 影响

- 前端聊天记录重复。
- Orchestrator history 包含重复 user message，可能影响 LLM 判断。
- SSE 重连时历史消息也会重复。

#### 修改方案

推荐方案：**API 层保存消息，Orchestrator 不再保存用户消息。**

修改 `paperforge/orchestrator/loop.py`：

```python
# 删除或改造这段
self.storage.add_message(
    run_id=run_id,
    role="user",
    content=user_message,
)
```

更好的方式是让 API route 传入 `message_id`：

```python
# api/routes/messages.py
message = storage.add_message(run_id=run_id, role="user", content=req.content)
asyncio.create_task(orchestrator.run(run_id=run_id, message_id=message["id"]))
```

Orchestrator 从 storage 读取最新消息即可。

#### 验收标准

发送一次消息后：

```sql
SELECT role, content FROM messages WHERE run_id = ?;
```

只应出现一条 user message。

---

### P0-3：新增 Artifacts API

#### 问题

现在工具层会保存 capability card、composition、PRD、nextjs app、verification report 等 artifacts，但后端没有清晰的 artifact REST API 给前端稳定读取。

#### 影响

- 前端只能从 tool result 里解析 JSON。
- artifact 展示和 timeline 无法稳定实现。
- SSE 断线重连后难以恢复工作台状态。

#### 修改方案

新增：

```text
api/routes/artifacts.py
```

端点：

```text
GET /api/runs/{run_id}/artifacts
GET /api/artifacts/{artifact_id}
```

示例：

```python
from fastapi import APIRouter, HTTPException
from paperforge.storage.db import get_storage

router = APIRouter()

@router.get("/runs/{run_id}/artifacts")
async def list_run_artifacts(run_id: str):
    storage = get_storage()
    return storage.list_artifacts(run_id=run_id)

@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str):
    storage = get_storage()
    artifact = storage.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact
```

在 `api/main.py` 注册：

```python
from api.routes import artifacts
app.include_router(artifacts.router, prefix="/api/artifacts", tags=["artifacts"])
```

#### 验收标准

生成 capability card 后，前端可以通过 API 读取 artifact，而不是依赖 tool result。

---

## 4. P1：打通最小端到端闭环

### P1-1：给 Orchestrator 加 phase/state gate

#### 问题

当前 Orchestrator 是自由 `LLM → tool → LLM` 循环，最多 20 次迭代。虽然灵活，但对 PaperForge 这种明确流程的产品来说不够稳定。

#### 风险

LLM 可能：

- 跳过 `parse_paper` 直接 `generate_nextjs_app`。
- 在没有 PRD 时调用 generator。
- verify 失败后直接 finish。
- 重复调用某个 tool，浪费 token 和时间。

#### 修改方案

保留 agentic loop，但增加 deterministic gate：

```python
from enum import Enum

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

ALLOWED_TOOLS = {
    RunPhase.INIT: {"parse_paper", "finish"},
    RunPhase.PARSED: {"compose_capabilities", "plan_product", "finish"},
    RunPhase.COMPOSED: {"plan_product", "finish"},
    RunPhase.PLANNED: {"generate_nextjs_app", "finish"},
    RunPhase.GENERATED: {"verify_app", "finish"},
    RunPhase.VERIFIED: {"run_in_sandbox", "generate_nextjs_app", "finish"},
    RunPhase.PREVIEW_READY: {"finish"},
}
```

在执行 tool 前：

```python
phase = storage.get_run_phase(run_id)
if call.name not in ALLOWED_TOOLS[phase]:
    result = {
        "ok": False,
        "error": f"Tool {call.name} not allowed in phase {phase}",
        "allowed_tools": list(ALLOWED_TOOLS[phase]),
    }
else:
    result = await dispatch_tool(...)
```

每个 tool 成功后更新 phase。

#### 验收标准

mock LLM 即使乱调用工具，Orchestrator 也不会跳过必要阶段。

---

### P1-2：统一 ToolResult schema

#### 问题

当前 tool handler 返回 dict，然后 dispatcher JSON dump。虽然可用，但缺少统一结构。有些 tool 返回 `artifact_id`，有些不返回；有些 error 是字符串，有些是 JSON。

#### 修改方案

新增统一 schema：

```python
class ToolResult(BaseModel):
    ok: bool
    tool: str
    artifact_id: str | None = None
    data: dict[str, Any] | None = None
    summary: str
    error: str | None = None
```

所有 handler 返回：

```python
return ToolResult(
    ok=True,
    tool="parse_paper",
    artifact_id=artifact_id,
    data={"card_id": paper_id},
    summary=f"Parsed paper {paper_id} into capability card.",
).model_dump()
```

给 LLM 的 tool result 可以只放 summary + artifact_id，完整 data 存 artifact。

#### 好处

- 前端事件展示更清晰。
- Orchestrator 可以根据 `ok` 决定是否进入下一 phase。
- 大 JSON 不再反复塞回 LLM context。

---

### P1-3：给 background task 做任务管理

#### 问题

`messages.py` 使用 `asyncio.create_task()` 启动 orchestrator，但没有保存 task 引用。

#### 影响

- 无法取消 run。
- 服务关闭时不好清理。
- task 出错只能日志记录，run status 不一定更新。

#### 修改方案

新增 `RunTaskManager`：

```python
class RunTaskManager:
    def __init__(self):
        self.tasks: dict[str, asyncio.Task] = {}

    def start(self, run_id: str, coro):
        if run_id in self.tasks and not self.tasks[run_id].done():
            raise RuntimeError("Run already active")
        task = asyncio.create_task(coro)
        self.tasks[run_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(run_id, None))
        return task

    def cancel(self, run_id: str):
        task = self.tasks.get(run_id)
        if task:
            task.cancel()
```

新增端点：

```text
POST /api/runs/{id}/cancel
```

---

## 5. P2：让生成 app 真的可运行

### P2-1：NextjsGenerator 改成 template-based

#### 问题

当前 `NextjsGenerator` 让 LLM 直接生成 `AppManifest.files`，然后逐个 `write_text()` 写文件。如果模型漏掉 `layout.tsx`、`globals.css`、Tailwind config、`tsconfig.json`、`next.config.mjs` 等文件，生成项目很容易 build 失败。

#### 修改方案

新增模板目录：

```text
paperforge/templates/nextjs_lightweight/
  package.json
  next.config.mjs
  tsconfig.json
  tailwind.config.ts
  postcss.config.js
  app/layout.tsx
  app/globals.css
  app/page.tsx
  app/api/predict/route.ts
  components/
  lib/mock-data.ts
  lib/adapter.ts
  README.md
  ADAPTER_CONTRACT.md
```

Generator 流程改成：

```text
1. copy template → output_dir
2. LLM 只生成 ProductSpec / PageSpec / MockData / AdapterSpec
3. 渲染或替换少量文件
4. 生成 manifest
```

不要让 LLM 每次从零生成整个 Next.js 工程。

#### 预期收益

- build 成功率明显提高。
- 生成结果风格统一。
- 更容易做 verifier 和 repair。

---

### P2-2：Verifier 必须真实执行 build

#### 问题

当前 `verify_app()` 注释写明“we can't run npm, so we check for essential files”，实际只判断 `package.json`、`app/`、`app/page.tsx` 是否存在。虽然文件里有 `run_build()`，但主验证逻辑没有真正使用它。

#### 修改方案

分两层验证：

```text
Level 1: static check
- package.json exists
- app/layout.tsx exists
- app/page.tsx exists
- no dangerous code
- mock/real adapter exists

Level 2: real build check
- npm install 或 npm ci
- npm run build
- collect stdout/stderr
```

建议不要在宿主机直接跑，而是在 Docker build sandbox 中跑：

```python
async def verify_app(...):
    static_report = static_check(app_path)
    build_report = await sandbox_manager.run_build_check(app_path)
    return merge_reports(static_report, build_report)
```

VerificationReport 增加：

```python
install_succeeded: bool
install_log_path: str | None
build_log_path: str | None
build_command: str
build_exit_code: int | None
```

#### 验收标准

`ready_for_preview=True` 的前提必须是：

```text
npm install / npm ci 成功
npm run build 成功
```

---

### P2-3：Sandbox 改成 build-first / preview-second

#### 问题

当前 Docker sandbox 启动命令是：

```bash
npm install --silent && npm run dev -- --port 3000 --hostname 0.0.0.0
```

这会导致：

- dev server 能启动，但 build 可能失败。
- install/build 日志和 preview 生命周期混在一起。
- preview 的 wow moment 不够可信。

#### 修改方案

拆成两个操作：

```text
verify_app:
  npm install
  npm run build

run_in_sandbox:
  npm run dev -- --port 3000 --hostname 0.0.0.0
```

DockerSandboxManager 增加：

```python
async def build_check(self, app_path: Path) -> BuildResult:
    ...

async def start_dev(self, run_id: str, app_path: Path) -> Sandbox:
    ...
```

Orchestrator 规则：

```text
只有 VerificationReport.ready_for_preview=True 时，才允许 run_in_sandbox。
```

---

### P2-4：Preview proxy 支持多 HTTP 方法

#### 问题

当前 Preview proxy 是：

```python
@router.get("/{sandbox_id}/{path:path}")
```

内部也只用 `client.get()` 转发。

#### 影响

生成的 full-stack app 如果有：

```text
POST /api/predict
POST /api/upload
PUT /api/settings
```

iframe 内部请求会失败。

#### 修改方案

改成：

```python
@router.api_route(
    "/{sandbox_id}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_preview(sandbox_id: str, path: str, request: Request):
    ...
    body = await request.body()
    resp = await client.request(
        request.method,
        target_url,
        headers=headers,
        content=body,
        timeout=30.0,
    )
```

同时增加根路径：

```python
@router.api_route("/{sandbox_id}", methods=[...])
async def proxy_preview_root(...):
    return await proxy_preview(sandbox_id, "", request)
```

---

## 6. P3：提升产品化质量

### P3-1：CapabilityCard 增加 evidence

#### 问题

PaperParser 现在直接把 PDF 文本截断到 80,000 字符，再让 LLM 输出 capability card。它没有保留 evidence trace。

#### 影响

后续 ProductPlanner / Composer 可能把论文没有明确说的内容当成事实，产品化建议容易“看起来合理但不忠于论文”。

#### 修改方案

Schema 增加：

```python
class Evidence(BaseModel):
    field: str
    section: str | None = None
    page: int | None = None
    quote: str

class CapabilityCard(BaseModel):
    ...
    evidence: list[Evidence] = []
```

PDF parser 改成保留 page 信息：

```python
pages = [{"page": i + 1, "text": page.get_text()} for i, page in enumerate(doc)]
```

Prompt 要求：

```text
For every key claim in problem/method/key_innovations/product_hints, include evidence with page and quote.
```

---

### P3-2：Composer 输出多个产品候选，而不是单一方向

#### 问题

PaperForge 的核心卖点是“多论文组合创新”，因此 Composer 不应该只输出一个 composition，而应该输出多个候选产品方向，让用户选择。

#### 修改方案

Composition schema 增强：

```python
class ProductCandidate(BaseModel):
    candidate_id: str
    name: str
    target_user: str
    user_job: str
    value_proposition: str
    paper_capabilities_used: list[str]
    mock_strategy: str
    real_integration_boundary: str
    feasibility_score: float
    novelty_score: float
    risk_score: float

class Composition(BaseModel):
    composition_id: str
    source_cards: list[str]
    synthesis_summary: str
    product_candidates: list[ProductCandidate]
```

前端新增 CandidateSelector：

```text
候选 A / B / C
- 用户价值
- 技术可行性
- mock 策略
- 真实模型接入边界
- 风险
```

用户选择后再进入 ProductPlanner。

---

### P3-3：ProductPlanner 支持 needs_more_input

#### 问题

当前 ProductPlanner 文件注释为 `single-shot`，没有 `needs_more_input` 或 `questions`。这和“混合交互 + 需求对谈”的产品目标不一致。

#### 修改方案

新增输出 wrapper：

```python
class PlannerOutput(BaseModel):
    needs_more_input: bool
    questions: list[str] = []
    prd: PRD | None = None
```

如果用户需求不足，返回：

```json
{
  "needs_more_input": true,
  "questions": [
    "目标用户是谁？",
    "demo 更偏科研工具还是普通用户产品？",
    "是否需要真实模型接入？"
  ],
  "prd": null
}
```

Orchestrator 遇到 `needs_more_input=true` 时，不继续 generate，而是把问题展示给用户。

---

## 7. P4：安全与工程质量

### P4-1：限制 read_file / write_file tool

#### 问题

Orchestrator tools 暴露了 `read_file` / `write_file`，描述为读写 project workspace。虽然有一定路径控制，但这种通用 tool 风险较高。

#### 修改方案

- 默认不把 `read_file` / `write_file` 暴露给 LLM orchestrator。
- 仅前端 CodeEditor 通过专用 files API 读写 sandbox app 文件。
- 如果必须给 LLM 使用，限制：
  - 只能访问 `workspace/runs/<run_id>/generated_apps/<app_id>/`
  - 禁止访问 `.env`、`node_modules`、`.next`、lockfile、二进制文件
  - 单文件最大 1MB
  - 所有写入生成 diff artifact

---

### P4-2：文件接口限制类型和大小

#### 问题

`api/routes/files.py` 已经做路径穿越检查，但没有明确限制文件类型、大小、二进制文件、`node_modules` 等。

#### 修改方案

增加：

```python
ALLOWED_EXTS = {".ts", ".tsx", ".js", ".jsx", ".json", ".css", ".md"}
BLOCKED_PARTS = {"node_modules", ".next", ".git"}
MAX_FILE_SIZE = 1_000_000
```

读写前检查：

```python
if any(part in BLOCKED_PARTS for part in full_path.parts):
    raise HTTPException(403, "Blocked path")
if full_path.suffix not in ALLOWED_EXTS:
    raise HTTPException(403, "Unsupported file type")
if full_path.exists() and full_path.stat().st_size > MAX_FILE_SIZE:
    raise HTTPException(413, "File too large")
```

---

### P4-3：给 approval 增加 timeout 和 cancel

#### 问题

当前 Orchestrator 对 dangerous tool 会等待 approval event。如果用户不点确认，run 可能一直挂起。

#### 修改方案

```python
try:
    await asyncio.wait_for(wait_event.wait(), timeout=300)
except asyncio.TimeoutError:
    approved = False
    result = "Approval timed out after 5 minutes."
```

前端提供：

```text
Approve / Reject / Cancel Run
```

---

## 8. 建议的新开发顺序

### Phase 1：先让项目能启动

目标：前后端都能启动，mock flow 不报错。

任务：

```text
1. 补 web/lib/api.ts、store.ts、types.ts、sse.ts、utils.ts
2. 修复 frontend build 错误
3. 修复 user message 重复保存
4. 增加 artifacts API
5. 增加最小 E2E mock test
```

验收：

```bash
python -m uvicorn api.main:app --reload
cd web && npm run build
pytest tests/integration/test_mock_flow.py
```

---

### Phase 2：让 Orchestrator 稳定

目标：mock LLM 下稳定走完整阶段。

任务：

```text
1. 加 RunPhase / ALLOWED_TOOLS
2. ToolResult 统一 schema
3. background task manager
4. approval timeout
5. EventTimeline 前端展示
```

验收：

```text
mock LLM 走 parse → compose/plan → generate → verify → preview/finish，事件流和 artifact 都能恢复。
```

---

### Phase 3：让生成 app 能 build

目标：生成的 Next.js app 不再只是文件，而是真能 build。

任务：

```text
1. 新增 nextjs_lightweight template
2. Generator 改成 template-based
3. Verifier 真正执行 npm install + npm run build
4. Preview sandbox 改成 build-first / preview-second
5. Preview proxy 支持多方法
```

验收：

```bash
cd generated_apps/app_xxx
npm install
npm run build
```

必须通过。

---

### Phase 4：增强产品化能力

目标：PaperForge 不只是 app generator，而是论文产品化工作台。

任务：

```text
1. CapabilityCard 增加 evidence
2. Composer 输出 2-3 个 product candidates
3. ProductPlanner 支持 needs_more_input + questions
4. 前端新增 CandidateSelector / CapabilityCardView / PRDView
5. Verification tab 展示 build log、PRD coverage、mock/real boundary
```

验收：

```text
用户可以上传论文 → 看 capability card → 选择候选产品 → 回答需求问题 → 生成 app → 查看 preview 和 verification report。
```

---

## 9. 推荐的最小验收用例

### 用例 1：Mock LLM E2E

```text
输入：mock paper path + “把这篇论文产品化”
输出：capability card、PRD、generated app manifest、verification report artifact
不要求 Docker preview
```

### 用例 2：Generated app build

```text
输入：固定 PRD fixture
输出：Next.js app
检查：npm install + npm run build 成功
```

### 用例 3：Preview proxy

生成 app 内包含：

```text
GET /
GET /_next/static/...
POST /api/predict
```

检查 proxy 是否全部转发成功。

### 用例 4：File safety

检查以下路径被拒绝：

```text
../.env
node_modules/react/index.js
.next/server/app.js
large_binary_file
```

---

## 10. 总结修改清单

### 立即修改

```text
[P0] 补 web/lib/*，修前端 build
[P0] 修 user message 重复保存
[P0] 增加 artifacts API
[P1] 增加 RunPhase gate
[P1] 统一 ToolResult schema
```

### 下一轮修改

```text
[P2] Generator 改成 template-based
[P2] Verifier 真正 npm build
[P2] Sandbox build-first / preview-second
[P2] Preview proxy 支持 POST/PUT/PATCH/DELETE/OPTIONS
[P2] 文件接口限制类型和大小
```

### 产品质量增强

```text
[P3] CapabilityCard 加 evidence
[P3] Composer 输出多个候选产品
[P3] ProductPlanner 支持 needs_more_input
[P3] 前端加 EventTimeline / CandidateSelector / Artifact panels
```

最终目标：

```text
不是让 PaperForge 看起来像有很多 agent，
而是让它真的稳定跑通：
PDF → Capability Card → Product Candidate → PRD → Next.js App → Build Verification → Live Preview。
```

