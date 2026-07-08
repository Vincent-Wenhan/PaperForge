# PaperForge

Repository: https://github.com/Vincent-Wenhan/PaperForge

PaperForge 是一个**论文产品化助手**。用户上传论文 PDF，系统通过多 agent 协作，生成可运行的 Next.js full-stack app，并在 Docker 沙箱中提供 live preview。

核心价值：**论文 → 可用产品** 的自动化转化。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLite (WAL) |
| 前端 | Next.js 14 App Router / TypeScript / Tailwind / shadcn/ui |
| LLM | 多 Provider（OpenAI / Anthropic / Westlake / DeepSeek） |
| 沙箱 | Docker（`node:20-alpine`） |
| 代码编辑器 | Monaco Editor |

## 项目结构

```
PaperForge/
├── paperforge/                # Python 包主目录
│   ├── orchestrator/          # 核心 orchestrator (loop / tools / events)
│   ├── agents/                # 5 个 sub-agent (paper_parser / composer / product_planner / nextjs_generator / verifier)
│   ├── llm/                   # 多 provider 抽象层
│   ├── sandbox/               # Docker 沙箱
│   ├── library/               # 论文库（持久化 capability cards）
│   ├── storage/               # SQLite + 文件存储
│   ├── schemas/               # Pydantic 数据模型
│   └── prompts/               # Agent prompts
│
├── api/                       # FastAPI 后端
├── web/                       # Next.js 前端
├── data/                      # 运行时数据（gitignored）
└── docs/                      # 设计文档（00-overview ~ 07-data-model）
```

## 核心架构

### 1. 自写 Orchestrator（不用 LangGraph）

一个 while loop 实现 agentic loop：

```python
async def run_orchestrator(run_id, user_message, history, emit):
    messages = history + [{"role": "user", "content": user_message}]
    while True:
        response = await llm.chat(model=config.ORCHESTRATOR_MODEL, messages=messages, tools=TOOL_DEFINITIONS)
        if response.tool_calls:
            for call in response.tool_calls:
                emit.tool_call(call.name, call.args)
                result = await dispatch_tool(call.name, call.args, run_id, emit)
                emit.tool_result(call.name, result)
                messages.append({"role": "assistant", "tool_calls": [call]})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            continue
        emit.text(response.content)
        messages.append({"role": "assistant", "content": response.content})
        return
```

关键设计：
- **无状态循环**：每轮 user message 启动一次循环，结束就退出。状态全在 SQLite
- **Tool 优先**：LLM 返回 tool_calls 时立即执行，不等用户确认
- **HITL 在 tool 层**：危险 tool 执行前 emit `approval_request`，前端弹确认框

### 2. Sub-agent 即 Tool

5 个 sub-agent 注册为 orchestrator 的 tool：

| Tool | 对应 sub-agent | 输入 | 输出 |
|---|---|---|---|
| `parse_paper` | PaperParser | `pdf_path` | capability card JSON |
| `compose_capabilities` | Composer | `[card_id]` | 组合创新点 JSON |
| `plan_product` | ProductPlanner | `composition_id` + 用户需求 | PRD JSON |
| `generate_nextjs_app` | NextjsGenerator | `prd_id` | 生成的 app 文件路径 |
| `verify_app` | Verifier | `app_path` | verification report |
| `run_in_sandbox` / `stop_sandbox` | (sandbox) | `app_path` / `container_id` | preview URL / success |
| `read_file` / `write_file` | (filesystem) | path + content | success |

每个 sub-agent 的输出必须是**合法 JSON**且符合预定义 schema。

### 3. SSE 事件流

前端通过 SSE 接收 orchestrator 事件：

| 事件 | 时机 | 载荷 |
|---|---|---|
| `run.started` | 循环开始 | run_id |
| `message.delta` | LLM 流式输出 | text chunk |
| `tool.call` | tool 被调用 | name, args |
| `tool.result` | tool 返回 | name, result |
| `artifact.created` | 生成新 artifact | type, path |
| `approval.requested` | 危险操作需确认 | tool, args |
| `approval.resolved` | 用户已确认/拒绝 | approved |
| `run.finished` | 循环结束 | run_id |
| `run.error` | 循环出错 | error message |
| `sandbox.started` | 沙箱启动 | sandbox_id |
| `sandbox.error` | 沙箱出错 | error message |
| `preview.ready` | 预览就绪 | url |

### 4. LLM 抽象层

```python
class LLMClient(Protocol):
    async def chat(self, model, messages, tools, stream: bool) -> Response: ...
    async def stream(self, model, messages, tools) -> AsyncIterator[Chunk]: ...
```

Provider 实现：
- `OpenAIProvider`：原生 `openai` SDK，支持 function calling
- `AnthropicProvider`：原生 `anthropic` SDK，支持 tool use
- `OpenAICompatibleProvider`：处理 Westlake/DeepSeek 等 OpenAI 兼容接口

Factory 通过 `LLM_PROVIDER` env var 切换 LLM 后端。

### 5. 数据模型（SQLite + 文件系统）

```sql
CREATE TABLE runs (id TEXT PRIMARY KEY, title TEXT, status TEXT, created_at, updated_at);
CREATE TABLE messages (id INTEGER PRIMARY KEY, run_id TEXT, role TEXT, content TEXT, tool_calls TEXT, tool_call_id TEXT, created_at);
CREATE TABLE sandboxes (id TEXT PRIMARY KEY, run_id TEXT, container_id TEXT, app_path TEXT, preview_port INTEGER, status TEXT, created_at, started_at, stopped_at);
CREATE TABLE papers (paper_id TEXT PRIMARY KEY, title TEXT, pdf_path TEXT, card_path TEXT, status TEXT, created_at, parsed_at);
CREATE TABLE artifacts (id TEXT PRIMARY KEY, run_id TEXT, type TEXT, path TEXT, metadata TEXT, created_at);
```

设计原则：
- SQLite 存元数据，文件系统存大内容
- 每个 artifact 一个 JSON 文件
- WAL 模式，多读单写

## 关键命令

```bash
# 后端
python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# 前端
cd web && npm run dev

# 测试
pytest tests/
```

## 设计规则

1. **自写 orchestrator**（不用 LangGraph）：一个 while loop 实现 agentic loop
2. **Sub-agent 即 tool**：每个 sub-agent 注册为 orchestrator 的 tool
3. **SSE 事件流**：前端通过 SSE 接收 orchestrator 事件
4. **SQLite 持久化**：元数据用 SQLite，大内容用文件
5. **多 Provider**：通过 `LLM_PROVIDER` env var 切换 LLM 后端
6. **错误处理**：LLM 失败重试 3 次（指数退避），Tool 失败把错误喂回 LLM，沙箱失败 emit 事件继续
7. **Mock-first**：原型默认 mock 模型能力，真实集成需要手动编辑 adapter

## Commit Convention

All commits must follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>
```

Types: `feat`, `fix`, `docs`, `refactor`, `chore`, `style`, `test`, `perf`.
Scope: the module being changed (e.g. `agent`, `tool`, `ui`, `doc`).

Examples:
- `docs(readme): add install and usage instructions`
- `feat(agent): add debug agent for log diagnosis`
- `fix(runner): handle timeout edge case`

## Git User

This repo is pushed by different contributors. Before committing, check that `git config user.name` and `user.email` are set to the intended identity.

## 设计文档

完整设计文档位于 `docs/` 目录：

| 文档 | 内容 |
|---|---|
| `00-overview.md` | 项目概述、技术栈、5 个 sub-agents 表、架构图 |
| `01-project-structure.md` | 完整目录结构、关键设计决策 |
| `02-orchestrator.md` | Orchestrator 主循环、tools 定义、SSE 事件表、LLM 抽象层 |
| `03-sub-agents.md` | 5 个 sub-agents 的详细设计（input/output schema、prompt 模板） |
| `04-sandbox-preview.md` | Docker 容器策略、端口分配、preview URL 流程、HMR、安全边界 |
| `05-frontend-ui.md` | 三栏 IDE 布局、组件清单、Zustand 状态管理、SSE 客户端 |
| `06-backend-api.md` | FastAPI 应用结构、所有路由实现、SSE 事件流 |
| `07-data-model.md` | 存储层次、完整 SQLite schema、Storage 类实现 |
