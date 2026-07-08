# PaperForge - Project Structure

## 完整目录结构

```
paperforge/
├── pyproject.toml              # 用 uv 或 pip-tools 管理依赖
├── .env.example
├── README.md
│
├── paperforge/                # Python 包主目录
│   ├── __init__.py
│   ├── config.py              # 环境变量配置
│   ├── orchestrator/          # 核心 orchestrator
│   │   ├── __init__.py
│   │   ├── loop.py            # 主循环：LLM → tool → LLM
│   │   ├── tools.py           # Orchestrator 可调用的 tools（= sub-agents）
│   │   └── events.py          # 事件发射器（SSE 用）
│   │
│   ├── agents/                # 5 个 sub-agent，每个一个文件
│   │   ├── paper_parser.py
│   │   ├── composer.py
│   │   ├── product_planner.py
│   │   ├── nextjs_generator.py
│   │   └── verifier.py
│   │
│   ├── llm/                   # 多 provider 抽象层
│   │   ├── __init__.py
│   │   ├── base.py            # LLMClient 抽象基类
│   │   ├── openai_provider.py
│   │   ├── anthropic_provider.py
│   │   └── factory.py         # 根据 env var 返回对应 provider
│   │
│   ├── sandbox/               # Docker 沙箱
│   │   ├── __init__.py
│   │   ├── docker_runner.py   # 在容器里跑 npm run dev
│   │   └── preview.py         # 返回 preview URL
│   │
│   ├── library/               # 论文库（持久化 capability cards）
│   │   └── .gitkeep
│   │
│   ├── storage/               # SQLite + 文件存储
│   │   ├── __init__.py
│   │   ├── db.py              # SQLite 连接 + schema
│   │   └── artifacts.py       # 生成代码的文件存储
│   │
│   └── prompts/               # Agent prompts
│       ├── orchestrator.md
│       ├── paper_parser.md
│       ├── composer.md
│       ├── product_planner.md
│       ├── nextjs_generator.md
│       └── verifier.md
│
├── api/                       # FastAPI 后端
│   ├── __init__.py
│   ├── main.py                # FastAPI app
│   ├── routes/
│   │   ├── runs.py            # 创建/列出 runs
│   │   ├── messages.py        # 发送消息
│   │   ├── events.py          # SSE 事件流
│   │   └── preview.py         # 获取 preview URL
│   └── deps.py                # 依赖注入
│
├── web/                       # Next.js 前端
│   ├── package.json
│   ├── next.config.mjs
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx           # 主工作台
│   │   ├── runs/[id]/page.tsx # 单个 run 的对话+预览
│   │   └── api/               # Next.js API routes（代理到 FastAPI）
│   ├── components/
│   │   ├── Sidebar.tsx        # 论文库 + Runs 列表
│   │   ├── ChatPanel.tsx      # 对话区
│   │   ├── PreviewPanel.tsx   # iframe 预览生成的 app
│   │   ├── CodeEditor.tsx     # 代码编辑器（Monaco）
│   │   └── ui/                # 基础组件（shadcn/ui）
│   └── lib/
│       ├── api.ts             # FastAPI 客户端
│       ├── sse.ts             # SSE 客户端
│       └── utils.ts
│
└── tests/
    ├── unit/                  # 单元测试
    ├── integration/           # 集成测试
    └── e2e/                   # E2E 测试
```

## 技术栈详情

### 后端
- **Python 3.11+**：用 asyncio + type hints
- **FastAPI**：现代 async web framework
- **SQLite**：嵌入式数据库，WAL 模式
- **Docker SDK for Python**：`docker` 包
- **Pydantic v2**：数据验证和序列化
- **httpx**：异步 HTTP 客户端（用于 preview 代理）

### 前端
- **Next.js 14 App Router**：React 18+ 全栈框架
- **TypeScript 5+**：类型安全
- **Tailwind CSS**：原子化 CSS
- **shadcn/ui**：基于 Radix UI 的复制粘贴组件库
- **Zustand**：轻量级状态管理
- **Monaco Editor**：VS Code 的编辑器内核
- **react-markdown** + **react-syntax-highlighter**：Markdown 渲染

### LLM Provider
- **OpenAI**：`openai` SDK，原生 function calling
- **Anthropic**：`anthropic` SDK，原生 tool use
- **OpenAI-Compatible**：处理 DeepSeek、Westlake 等兼容接口

## 关键设计决策

### 1. 自写 Orchestrator（不用 LangGraph）

**理由**：
- LangGraph 的状态机模式不适合 agentic loop
- 自写 while loop 更简单、更可控、更易调试
- 代码量约 200 行

**实现**：
```python
# paperforge/orchestrator/loop.py

async def run_orchestrator(
    run_id: str,
    user_message: str,
    history: list[Message],
    emit: EventEmitter,
) -> None:
    """主循环：LLM → tool → LLM，直到 LLM 不再调用 tool 或调用 finish。"""
    messages = history + [{"role": "user", "content": user_message}]
    
    while True:
        emit.text("thinking...")
        response = await llm.chat(
            model=config.ORCHESTRATOR_MODEL,
            messages=messages,
            tools=TOOL_DEFINITIONS,
        )
        
        # 1. LLM 返回 tool 调用 → 执行 tool → 结果喂回
        if response.tool_calls:
            for call in response.tool_calls:
                emit.tool_call(call.name, call.args)
                result = await dispatch_tool(call.name, call.args, run_id, emit)
                emit.tool_result(call.name, result)
                messages.append({"role": "assistant", "tool_calls": [call]})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            continue
        
        # 2. LLM 返回文本 → 推给前端 → 等待下一轮用户输入
        emit.text(response.content)
        messages.append({"role": "assistant", "content": response.content})
        storage.save_messages(run_id, messages)
        return  # 结束本轮，等下一个用户消息
```

### 2. Sub-agent 即 Tool

每个 sub-agent 是一个 async 函数，签名固定：`(args: dict, ctx: ToolContext) -> str`。返回值是给 LLM 看的字符串。

```python
TOOL_DEFINITIONS = [
    {
        "name": "parse_paper",
        "description": "Parse PDF and extract capability card. Returns card_id and card JSON.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string", "description": "Path to PDF file"},
                "paper_id": {"type": "string", "description": "Optional paper ID"},
            },
            "required": ["pdf_path"],
        },
    },
    # ... 其他 4 个 sub-agent
]

async def dispatch_tool(name: str, args: dict, ctx: ToolContext) -> str:
    """根据 tool name 分发到对应 handler"""
    handlers = {
        "parse_paper": handle_parse_paper,
        "compose_capabilities": handle_compose,
        "plan_product": handle_plan_product,
        "generate_nextjs_app": handle_generate,
        "verify_app": handle_verify,
        "run_in_sandbox": handle_run_sandbox,
        "stop_sandbox": handle_stop_sandbox,
        "read_file": handle_read_file,
        "write_file": handle_write_file,
        "finish": handle_finish,
    }
    
    handler = handlers.get(name)
    if not handler:
        return f"Unknown tool: {name}"
    
    try:
        result = await handler(args, ctx)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"Tool error: {e}"
```

### 3. SSE 事件流

Orchestrator 通过 `EventEmitter` 发事件，后端 SSE 路由推给前端：

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

### 4. LLM 抽象层

```python
# paperforge/llm/base.py
class LLMClient(Protocol):
    async def chat(self, model, messages, tools, stream: bool) -> Response: ...
    async def stream(self, model, messages, tools) -> AsyncIterator[Chunk]: ...
```

**Provider 实现**：
- `OpenAIProvider`：原生 `openai` SDK，支持 function calling
- `AnthropicProvider`：原生 `anthropic` SDK，支持 tool use
- `OpenAICompatibleProvider`：处理 Westlake/DeepSeek 等 OpenAI 兼容接口

**Factory**：
```python
def get_llm_client() -> LLMClient:
    provider = os.getenv("LLM_PROVIDER", "openai")
    if provider == "anthropic":
        return AnthropicClient()
    elif provider == "openai_compatible":
        return OpenAICompatibleClient()
    return OpenAIClient()
```

### 5. 数据模型（SQLite）

```sql
-- 一个 run = 一次用户会话
CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    status TEXT  -- active / completed / error
);

-- 消息历史
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES runs(id),
    role TEXT,       -- user / assistant / tool
    content TEXT,
    tool_calls TEXT, -- JSON
    created_at TIMESTAMP
);

-- Artifacts（capability card / composition / PRD / generated app）
CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES runs(id),
    type TEXT,        -- capability_card / composition / prd / nextjs_app / verification_report
    path TEXT,        -- 文件系统路径
    metadata TEXT,    -- JSON
    created_at TIMESTAMP
);

-- 沙箱实例
CREATE TABLE sandboxes (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    container_id TEXT,
    preview_url TEXT,
    status TEXT,
    created_at TIMESTAMP
);
```

### 6. 错误处理

- **LLM 调用失败**：重试 3 次（指数退避），仍失败则 emit `run.error` 事件，结束循环
- **Tool 执行失败**：把错误信息作为 tool result 喂回 LLM，让 LLM 决定下一步（重试 / 换方案 / 问用户）
- **沙箱启动失败**：emit `sandbox.error`，orchestrator 继续，LLM 会看到错误

### 7. Orchestrator 的 system prompt

```
You are PaperForge, an orchestrator that turns research papers into 
Next.js full-stack apps.

You have 5 sub-agents available as tools:
1. parse_paper → extract capability card from PDF
2. compose_capabilities → combine multiple cards into new ideas
3. plan_product → refine product requirements (JTBD/PRD/MVP)
4. generate_nextjs_app → generate Next.js code from PRD
5. verify_app → check generated app builds and matches PRD

You also have sandbox tools to run/stop Docker containers.

Default flow when user uploads paper(s):
1. parse_paper for each PDF → save capability card
2. If multiple papers: compose_capabilities
3. plan_product (may need user dialogue)
4. generate_nextjs_app
5. verify_app
6. run_in_sandbox → return preview URL

Be proactive: if information is missing, ask the user.
If a step fails, try to recover before asking the user.
```

### 8. 前端交互流程

```
用户上传 paper.pdf
    ↓
前端 POST /api/runs （创建 run）
    ↓
前端 POST /api/runs/{id}/messages {content: "请把这个论文产品化"}
    ↓
后端启动 orchestrator，返回 SSE stream
    ↓
Orchestrator 调用 parse_paper → capability card JSON
    ↓
emit tool.call / tool.result → 前端展示 capability card
    ↓
Orchestrator 调用 generate_nextjs_app → app 文件
    ↓
Orchestrator 调用 run_in_sandbox → preview URL
    ↓
emit preview.ready → 前端 iframe 展示 preview
    ↓
Orchestrator 返回总结文本 → 前端展示
```

---

## 关键决策总结

1. **自写 orchestrator**（不用 LangGraph）：一个 while loop 实现 agentic loop
2. **Sub-agent 即 tool**：每个 sub-agent 注册为 orchestrator 的 tool
3. **SSE 事件流**：前端通过 SSE 接收 orchestrator 事件
4. **SQLite 持久化**：元数据用 SQLite，大内容用文件
5. **多 Provider**：通过 `LLM_PROVIDER` env var 切换 LLM 后端
6. **Docker 沙箱**：每个生成的 app 在独立容器中运行
