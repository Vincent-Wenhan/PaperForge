# PaperForge - Overview

## 项目定位

PaperForge 是一个**论文产品化助手**。用户上传论文 PDF，系统通过多 agent 协作，生成可运行的 Next.js full-stack app，并在 Docker 沙箱中提供 live preview。

核心价值：**论文 → 可用产品** 的自动化转化。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLite |
| 前端 | Next.js 14 App Router / TypeScript / Tailwind / shadcn/ui |
| LLM | 多 Provider（OpenAI / Anthropic / DeepSeek / Westlake） |
| 沙箱 | Docker（`node:20-alpine`） |
| 代码编辑器 | Monaco Editor |

## 架构总览

```
[Next.js App Router] ←SSE→ [FastAPI orchestrator]
                              ↓ tool calls
                    [5 sub-agents + tools]
                              ↓
                    [Docker sandbox]
                              ↓
                    [Generated Next.js app preview]
```

### 三大运行时层

1. **Backend（`api/`）** — FastAPI 应用。`api/main.py` 创建 app、注册路由、启动沙箱监控。SSE 路由推事件给前端。
2. **Frontend（`web/`）** — Next.js 工作台。三栏 IDE 风布局：Sidebar + Chat + Preview。通过 SSE 接收 orchestrator 事件。
3. **Core（`paperforge/`）** — Python 包。包含 orchestrator、agents、llm、sandbox、storage 等核心模块。

### 5 个 Sub-agents

| Agent | 职责 | 输入 | 输出 |
|---|---|---|---|
| PaperParser | PDF → capability card | pdf_path | card JSON |
| Composer | 多 card 组合创新 | [card_id] | composition JSON |
| ProductPlanner | 精炼 PRD（多轮对话） | composition + 用户需求 | PRD JSON |
| NextjsGenerator | PRD → Next.js app 文件 | prd_id | app manifest |
| Verifier | 检查 app 可 build、符合 PRD | app_path | verification report |

## 项目结构

```
Project/
├── README.md
├── pyproject.toml
├── .env.example
│
├── paperforge/                # Python 包
│   ├── orchestrator/          # Orchestrator + tools + events
│   ├── agents/                # 5 个 sub-agent
│   ├── llm/                   # 多 provider 抽象
│   ├── sandbox/               # Docker 沙箱
│   ├── storage/               # SQLite + 文件存储
│   ├── schemas/               # Pydantic 数据模型
│   └── prompts/               # Agent prompts
│
├── api/                       # FastAPI 后端
│   ├── main.py
│   └── routes/
│
├── web/                       # Next.js 前端
│   ├── app/
│   ├── components/
│   └── lib/
│
├── data/                      # 运行时数据（gitignored）
│   ├── paperforge.db
│   ├── library/
│   ├── generated_apps/
│   └── ...
│
└── docs/                      # 设计文档
    ├── 00-overview.md
    ├── 01-project-structure.md
    ├── 02-orchestrator.md
    ├── 03-sub-agents.md
    ├── 04-sandbox-preview.md
    ├── 05-frontend-ui.md
    ├── 06-backend-api.md
    └── 07-data-model.md
```

## 核心设计决策

1. **自写 orchestrator**：不用 LangGraph，一个简单的 while loop 实现 agentic loop
2. **Sub-agent 即 tool**：每个 sub-agent 注册为 orchestrator 的 tool
3. **SSE 事件流**：前端通过 SSE 接收 orchestrator 事件
4. **Docker 沙箱**：每个生成的 app 在独立容器中运行
5. **多 Provider**：通过 `LLM_PROVIDER` env var 切换 LLM 后端
6. **SQLite + 文件系统**：元数据用 SQLite，大内容用文件

## 交付节奏

按模块交付：
1. 项目骨架 + LLM 抽象层
2. PaperParser + 论文库
3. Composer + ProductPlanner
4. NextjsGenerator
5. Verifier
6. Sandbox + Preview
7. Frontend Web UI
8. 集成测试 + 文档
