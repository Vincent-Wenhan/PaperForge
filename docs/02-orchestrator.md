# PaperForge - Orchestrator Design

Orchestrator 是整个系统的心脏。核心思路：**一个 agent + 一组 tools（sub-agents + sandbox）+ 一个事件流**。

## 1. 主循环

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
            tools=TOOL_DEFINITIONS,   # 5 个 sub-agent + sandbox_control
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

**关键设计**：
- **无状态循环**：每轮 user message 启动一次循环，结束就退出。状态全在 SQLite
- **Tool 优先**：LLM 返回 tool_calls 时立即执行，不等用户确认
- **HITL 在 tool 层**：危险 tool（如 `generate_app`、`run_in_sandbox`）执行前会 emit 一个 `approval_request` 事件，前端弹确认框

## 2. Tools 定义（5 个 sub-agent + 沙箱控制）

每个 tool 是一个 async 函数，签名固定：`(args: dict, ctx: ToolContext) -> str`。返回值是给 LLM 看的字符串。

| Tool | 对应 sub-agent | 输入 | 输出 |
|---|---|---|---|
| `parse_paper` | PaperParser | `pdf_path` | capability card JSON |
| `compose_capabilities` | Composer | `[card_id]` | 组合创新点 JSON |
| `plan_product` | ProductPlanner | `composition_id` + 用户需求 | PRD JSON |
| `generate_nextjs_app` | NextjsGenerator | `prd_id` | 生成的 app 文件路径 |
| `verify_app` | Verifier | `app_path` | verification report |
| `run_in_sandbox` | (sandbox) | `app_path` | preview URL + 容器 ID |
| `stop_sandbox` | (sandbox) | `container_id` | success |
| `read_file` / `write_file` | (filesystem) | path + content | success |

**Tool 注册**：
```python
TOOL_DEFINITIONS = [
    {
        "name": "parse_paper",
        "description": "解析 PDF，提取 capability card（方法/指标/数据/限制）",
        "input_schema": {"type": "object", "properties": {"pdf_path": {"type": "string"}}, "required": ["pdf_path"]},
    },
    # ... 其他 8 个
]

TOOL_HANDLERS = {
    "parse_paper": handle_parse_paper,
    "compose_capabilities": handle_compose,
    # ...
}
```

## 3. 事件流（SSE）

Orchestrator 通过 `EventEmitter` 发事件，后端 SSE 推给前端：

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

## 4. LLM 抽象层

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

## 5. 数据模型（SQLite）

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

## 6. 错误处理

- **LLM 调用失败**：重试 3 次（指数退避），仍失败则 emit `run.error` 事件，结束循环
- **Tool 执行失败**：把错误信息作为 tool result 喂回 LLM，让 LLM 决定下一步（重试 / 换方案 / 问用户）
- **沙箱启动失败**：emit `sandbox.error`，orchestrator 继续，LLM 会看到错误

## 7. Orchestrator 的 system prompt

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

## 8. 前端交互流程

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
6. **错误处理**：LLM 失败重试，Tool 失败喂回 LLM，沙箱失败继续
