# PaperForge - Sub-agents Design

每个 sub-agent = 一个 prompt + 一个 schema + 一个 LLM 调用。返回结构化 JSON，orchestrator 把 JSON 串作为 tool result 喂回 LLM。

## 1. PaperParser（论文解析）

**职责**：PDF → capability card JSON

**输入**：
```python
{
    "pdf_path": "uploads/attention_is_all_you_need.pdf",
    "paper_id": "attention_2017"  # 可选，不传则从文件名推断
}
```

**输出（capability card schema）**：
```python
class CapabilityCard(BaseModel):
    paper_id: str                    # 唯一标识
    title: str
    authors: list[str]
    year: int
    
    # 核心能力
    problem: str                     # 解决什么问题
    method: str                      # 核心方法（1-2 句话）
    key_innovations: list[str]       # 关键创新点
    inputs: list[str]                # 输入数据类型
    outputs: list[str]               # 输出数据类型
    metrics: list[Metric]            # 评估指标
    
    # 产品化线索
    capability_category: str         # image_classification / text_generation / ...
    reusable_components: list[str]   # 可复用的组件（如 attention layer）
    product_hints: list[str]         # 产品化方向提示
    
    # 限制
    constraints: list[str]           # 运行约束（GPU、数据量）
    dependencies: list[str]          # 关键依赖（PyTorch、Transformers）

class Metric(BaseModel):
    name: str
    value: str
    context: str                     # 在什么条件下达到
```

**Prompt 要点**：
- 只从 PDF 原文提取，不编造
- 不确定的字段用 `null` 或 `"unknown"`
- 输出必须是合法 JSON，schema 见上

**实现**：
```python
# paperforge/agents/paper_parser.py
async def parse_paper(pdf_path: str, paper_id: str | None = None) -> dict:
    text = extract_pdf_text(pdf_path)  # PyMuPDF
    paper_id = paper_id or Path(pdf_path).stem
    
    response = await llm.chat(
        model=config.PARSER_MODEL,
        messages=[
            {"role": "system", "content": PARSER_PROMPT},
            {"role": "user", "content": f"Paper ID: {paper_id}\n\n{text}"},
        ],
        response_format={"type": "json_object"},
    )
    
    card = CapabilityCard.model_validate_json(response.content)
    
    # 持久化到论文库
    library.save_card(card)
    storage.save_artifact(run_id, "capability_card", card.model_dump())
    
    return {"card_id": paper_id, "card": card.model_dump()}
```

**从现有项目复用**：
- `tools/pdf_parser.py` → `paperforge/agents/pdf_parser.py`（PyMuPDF 提取）
- `tools/llm_client.py` → 简化后作为 `llm/base.py`

---

## 2. Composer（多论文组合）

**职责**：多个 capability card → 组合创新点 JSON

**输入**：
```python
{
    "card_ids": ["attention_2017", "vae_2013", "clip_2021"]
}
```

**输出（composition schema）**：
```python
class Composition(BaseModel):
    composition_id: str
    source_cards: list[str]
    
    # 组合创新
    novel_idea: str                  # 组合产生的新能力
    combination_mechanism: str       # 如何组合（串联/并联/嵌入）
    emergent_capability: str         # 组合后涌现的新能力
    
    # 产品化方向
    product_concepts: list[ProductConcept]
    
    # 风险
    technical_risks: list[str]
    integration_challenges: list[str]

class ProductConcept(BaseModel):
    name: str
    user_job: str                    # JTBD
    target_users: list[str]
    value_proposition: str
    mvp_scope: str                   # MVP 包含什么
    mock_strategy: str               # 如何 mock
```

**Prompt 要点**：
- 不是简单叠加，要找到组合涌现
- 每个概念必须有 user_job 和 mvp_scope
- 输出合法 JSON

---

## 3. ProductPlanner（产品规划）

**职责**：与用户对话，精炼 PRD/MVP。**这是唯一需要多轮对话的 sub-agent**。

**输入**：
```python
{
    "composition_id": "comp_001",
    "user_requirement": "我想做一个能根据文字描述生成图像的应用",
    "dialogue_history": [...]  # 可选
}
```

**输出（PRD schema）**：
```python
class PRD(BaseModel):
    prd_id: str
    composition_id: str
    
    # 产品定义
    product_name: str
    one_liner: str                   # 一句话定义
    target_users: list[str]
    user_jobs: list[str]             # JTBD
    value_proposition: str
    
    # 功能范围（MoSCoW）
    must_have: list[Feature]
    should_have: list[Feature]
    could_have: list[Feature]
    wont_have: list[str]
    
    # 技术约束
    mock_strategy: str               # 如何 mock 模型能力
    data_strategy: str               # 数据从哪来
    performance_targets: dict        # 响应时间/吞吐
    
    # UI/UX 方向
    ui_style: str                    # minimal / dashboard / playful
    key_screens: list[str]           # 关键页面描述

class Feature(BaseModel):
    name: str
    description: str
    acceptance_criteria: list[str]
```

**多轮对话机制**：
```python
# paperforge/agents/product_planner.py
async def plan_product(composition_id, user_requirement, dialogue_history=None):
    if dialogue_history is None:
        dialogue_history = []
    
    # 如果没有历史，开始新对话
    if not dialogue_history:
        messages = [
            {"role": "system", "content": PLANNER_PROMPT},
            {"role": "user", "content": f"Composition: {composition}\n\nUser: {user_requirement}"},
        ]
    else:
        messages = dialogue_history
    
    response = await llm.chat(
        model=config.PLANNER_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
    )
    
    # 返回 PRD 或需要继续对话的信号
    return {"prd": prd.model_dump(), "needs_more_input": False}
```

---

## 4. NextjsGenerator（代码生成）

**职责**：PRD → Next.js full-stack app

**输入**：
```python
{
    "prd_id": "prd_001",
    "output_dir": "generated_apps/app_001"
}
```

**输出（app manifest schema）**：
```python
class AppManifest(BaseModel):
    app_id: str
    prd_id: str
    
    # 文件结构
    files: list[AppFile]
    dependencies: dict[str, str]     # package.json dependencies
    
    # 运行配置
    scripts: dict[str, str]
    env_example: dict[str, str]
    
    # 模型集成
    mock_adapters: list[str]         # mock adapter 文件路径
    real_adapters: list[str]         # real adapter 文件路径
    
    # 预览信息
    preview_port: int                # 默认 3000
    preview_route: str               # 默认 /

class AppFile(BaseModel):
    path: str                        # 相对路径，如 app/page.tsx
    content: str
    description: str                 # 这个文件的作用
```

**Prompt 要点**：
- 生成 App Router 结构（`app/` 目录）
- 每个文件独立生成，避免一次性生成整个 app
- mock adapter 和 real adapter 分离，real adapter 有 TODO 标注
- UI 用 Tailwind + shadcn/ui
- API routes 用 Next.js Route Handlers
- 状态管理用 React Hook（除非复杂场景用 Zustand）

**生成策略（分步生成）**：
```python
async def generate_nextjs_app(prd_id, output_dir):
    prd = storage.get_artifact(prd_id)
    
    # 1. 生成项目结构
    manifest = await llm.chat(
        model=config.GENERATOR_MODEL,
        messages=[
            {"role": "system", "content": GENERATOR_PROMPT},
            {"role": "user", "content": f"PRD: {prd.model_dump_json()}"},
        ],
        response_format={"type": "json_object"},
    )
    
    # 2. 写文件
    app_dir = Path(output_dir)
    for f in manifest.files:
        (app_dir / f.path).parent.mkdir(parents=True, exist_ok=True)
        (app_dir / f.path).write_text(f.content)
    
    # 3. 写 package.json / next.config.mjs / tailwind.config.ts
    ...
    
    # 4. 安装依赖
    await run_command(f"cd {app_dir} && npm install")
    
    return {"app_id": manifest.app_id, "app_path": str(app_dir)}
```

---

## 5. Verifier（验证）

**职责**：检查生成的 app 是否可 build、是否符合 PRD、mock/real boundary 是否清楚

**输入**：
```python
{
    "app_path": "generated_apps/app_001",
    "prd_id": "prd_001"
}
```

**输出（verification report schema）**：
```python
class VerificationReport(BaseModel):
    app_id: str
    prd_id: str
    
    # 构建检查
    build_succeeded: bool
    build_errors: list[str]
    build_warnings: list[str]
    
    # PRD 对齐
    prd_coverage: float              # 0-1，PRD 中 must_have 的覆盖率
    missing_features: list[str]
    extra_features: list[str]
    
    # Mock/Real 边界
    mock_adapters_count: int
    real_adapters_count: int
    boundary_clear: bool             # mock 和 real 是否清晰分离
    boundary_issues: list[str]
    
    # 代码质量
    type_errors: list[str]
    lint_errors: list[str]
    
    # 安全
    security_issues: list[str]       # XSS / hardcoded secrets / etc
    
    # 整体评分
    overall_score: float             # 0-1
    ready_for_preview: bool
    recommendations: list[str]
```

**Prompt 要点**：
- 先跑 `npm run build` 收集错误
- 对比 PRD 和生成的代码，找 gap
- 检查 mock/real 边界（mock adapter 不能混入 real 逻辑）
- 检查常见安全问题

---

## 6. 数据模型

**CapabilityCard**（上已定义）
**Composition**（上已定义）
**PRD**（上已定义）
**AppManifest**（上已定义）
**VerificationReport**（上已定义）

全部用 Pydantic，存在 `paperforge/schemas/` 下。

### Prompt 模板

存在 `paperforge/prompts/` 下，每个 sub-agent 一个 `.md` 文件。Prompt 里包含：
1. 角色定义
2. 输入说明
3. 输出 schema（JSON）
4. 示例输入输出
5. 约束（不编造、合法 JSON）

---

## 7. 测试策略

- **单元测试**：每个 sub-agent 的 schema validation、PDF 解析、JSON 解析
- **集成测试**：给一个简单 PDF，跑完 5 个 agent，验证输出 schema
- **E2E 测试**：上传 paper.pdf → orchestrator → preview URL → 验证预览可访问

---

## 8. 与现有项目的关系

**复用**：
- PDF 解析逻辑（`tools/pdf_parser.py`）
- LLM 客户端抽象（`tools/llm_client.py`）

**重写**：
- 所有 agents（从 10 个简化到 5 个）
- Pipeline（从 LangGraph 状态机改为 orchestrator loop）
- Backend（从 run_service 改为 event-driven orchestrator）
- Frontend（从 WorkspaceShell 改为 IDE 风 chat + preview）

**删除**：
- `agents/legacy/` 目录
- `pipeline/` 下所有 LangGraph 相关代码
- `graphs/` 目录
- `productize/` 目录（功能合并到 NextjsGenerator）

---

## 9. 关键决策点

1. **Sub-agent 之间不直接通信**，只通过 orchestrator 传递 JSON
2. **每个 sub-agent 的输出必须是合法 JSON**，且符合预定义 schema
3. **ProductPlanner 是唯一需要多轮对话的 sub-agent**，其他都是 single-shot
4. **NextjsGenerator 分步生成**：先 manifest，再逐个文件
5. **Verifier 是独立的**，不参与 orchestrator 决策，只提供报告

---

## 10. Sub-agent 实现模板

每个 sub-agent 都遵循这个模板：

```python
# paperforge/agents/xxx.py

from paperforge.llm import get_llm_client
from paperforge.schemas.xxx import XxxOutput
from paperforge.prompts import load_prompt

async def run_xxx(input: XxxInput, ctx: AgentContext) -> dict:
    """Sub-agent: XXX
    
    输入: ...
    输出: ...
    """
    llm = get_llm_client()
    prompt = load_prompt("xxx")
    
    response = await llm.chat(
        model=config.XXX_MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": input.model_dump_json()},
        ],
        response_format={"type": "json_object"},
    )
    output = XxxOutput.model_validate_json(response.content)
    
    # 持久化
    storage.save_artifact(ctx.run_id, "xxx_output", output.model_dump())
    
    return {"xxx_id": output.xxx_id, "xxx": output.model_dump()}
```

---

## 11. Sub-agent 之间的依赖关系

```
PaperParser (PDF → card)
    ↓
Composer (cards → composition)
    ↓
ProductPlanner (composition → PRD)
    ↓
NextjsGenerator (PRD → app files)
    ↓
Verifier (app → verification report)
```

Orchestrator 按这个顺序调用，但可以根据 LLM 的决策跳过或重复某些步骤。

---

## 12. Sub-agent 的 tool 注册

```python
# paperforge/orchestrator/tools.py

SUBAGENT_TOOLS = [
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

---

## 13. Sub-agent 的 prompt 模板

每个 sub-agent 的 prompt 都遵循这个结构：

```markdown
# Paper Parser

You are a research paper parser. Your job is to extract a capability card from a PDF.

## Input

You will receive:
- Paper ID: unique identifier
- Paper text: extracted from PDF

## Output

Return a JSON object with this schema:

```json
{
  "paper_id": "string",
  "title": "string",
  ...
}
```

## Rules

1. Only extract information that is explicitly stated in the paper.
2. If a field is not mentioned, use `null` or `"unknown"`.
3. Do not fabricate information.
4. Output must be valid JSON.

## Example

Input:
```
Paper ID: attention_2017
Paper text: ...
```

Output:
```json
{
  "paper_id": "attention_2017",
  "title": "Attention Is All You Need",
  ...
}
```
```

---

## 14. Sub-agent 的错误处理

- **LLM 返回非法 JSON**：retry 3 次，仍失败则返回 `{"error": "Failed to parse LLM output"}`
- **Schema validation 失败**：retry 3 次，仍失败则返回 `{"error": "Schema validation failed", "details": e.errors()}`
- **PDF 解析失败**：返回 `{"error": "Failed to parse PDF"}`，orchestrator 决定是否继续

---

## 15. 完整的 API 端点清单

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/runs | 创建 run |
| GET | /api/runs | 列出 runs |
| GET | /api/runs/{id} | 获取 run 详情 |
| DELETE | /api/runs/{id} | 删除 run |
| POST | /api/runs/{id}/messages | 发送消息(异步启动 orchestrator) |
| GET | /api/runs/{id}/messages | 列出消息历史 |
| GET | /api/runs/{id}/events | SSE 事件流 |
| GET | /api/library | 列出论文库 |
| POST | /api/library/upload | 上传 PDF |
| GET | /api/library/{paper_id} | 获取论文及 capability card |
| DELETE | /api/library/{paper_id} | 删除论文 |
| POST | /api/sandboxes | 启动沙箱 |
| GET | /api/sandboxes/{id} | 获取沙箱状态 |
| POST | /api/sandboxes/{id}/stop | 停止沙箱 |
| POST | /api/sandboxes/{id}/restart | 重启沙箱 |
| GET | /api/sandboxes/{id}/logs | SSE 容器日志流 |
| GET | /api/preview/{sandbox_id}/{path} | 代理 preview 请求 |
| GET | /api/files/sandboxes/{id}/tree | 获取文件树 |
| GET | /api/files/sandboxes/{id}/files/{path} | 读取文件 |
| PUT | /api/files/sandboxes/{id}/files/{path} | 写入文件 |
| GET | /api/settings | 获取设置(LLM provider、Docker 状态) |
