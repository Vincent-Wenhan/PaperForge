# PaperForge - Development Guide

本文件记录 PaperForge 项目的开发规范与约定。所有贡献者在提交代码前必须阅读本文档。

## 1. Commit Convention

所有提交必须遵循 [Conventional Commits](https://www.conventionalcommits.org/)：

```
<type>(<scope>): <subject>

[optional body]

[optional footer(s)]
```

### Types

| Type | 用于 |
|---|---|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档变更 |
| `refactor` | 不改变外部行为的代码重构 |
| `chore` | 构建 / 工具链 / 杂项 |
| `style` | 代码风格（空白、格式、分号等），不改逻辑 |
| `test` | 新增或修改测试 |
| `perf` | 性能优化 |

### Scope

模块名，小写，可选：

- `agent` / `orchestrator` / `llm` / `sandbox` / `storage` — paperforge 子模块
- `api` — FastAPI 后端
- `web` — Next.js 前端
- `doc` — 文档
- `test` — 测试
- `ci` — CI 配置

### Subject

- 祈使句，小写开头
- 不以句号结尾
- 最长 72 字符

### 示例

```
feat(agent): add PaperParser to extract capability card
fix(sandbox): handle docker daemon not running
docs(readme): add quick start section
refactor(orchestrator): extract tool dispatch into separate module
test(llm): add mock provider for unit tests
chore(ci): add github actions workflow
```

## 2. Branch Strategy

### Branch naming

```
<type>/<short-description>
```

示例：
- `feat/paper-parser`
- `fix/sandbox-port-allocation`
- `docs/api-reference`

### Workflow

```bash
# Create a feature branch
git checkout -b feat/paper-parser

# Make changes and commit
git add paperforge/agents/paper_parser.py
git commit -m "feat(agent): add PaperParser to extract capability card"

# Push and create PR
git push -u origin feat/paper-parser
gh pr create --title "feat(agent): add PaperParser" --body "..."
```

## 3. Code Style

### Python (backend)

- **Formatter**: `ruff format`
- **Linter**: `ruff check`
- **Line length**: 100
- **Python version**: 3.11+
- **Type hints**: required on all function signatures
- **Docstrings**: only for public API, not for internal helpers

```python
# Good
async def parse_paper(pdf_path: Path, paper_id: str | None = None) -> CapabilityCard:
    """Parse a PDF and return a capability card."""
    text = extract_pdf_text(pdf_path)
    ...

# Bad - no type hints, no docstring on public function
async def parse_paper(pdf_path, paper_id=None):
    text = extract_pdf_text(pdf_path)
    ...
```

### TypeScript (frontend)

- **Formatter**: `prettier`
- **Linter**: `eslint`
- **Strict mode**: enabled
- **Import order**: `react` → third-party → `@/` internal

## 4. Testing Strategy

### Layered testing

| 层 | 何时写 | 工具 |
|---|---|---|
| **Unit tests** | 每个 sub-agent、schema、pure function | `pytest` |
| **Integration tests** | 模块间接口（orchestrator + agents） | `pytest` |
| **E2E tests** | 关键用户流程（upload → preview） | `pytest` + `httpx` |

### Test file naming

```
tests/
├── unit/
│   ├── test_paper_parser.py
│   └── test_capability_card_schema.py
├── integration/
│   └── test_orchestrator_with_agents.py
└── e2e/
    └── test_upload_and_preview.py
```

### Test structure (AAA pattern)

```python
def test_parse_paper_extracts_card():
    # Arrange
    pdf_path = Path("tests/fixtures/attention_is_all_you_need.pdf")
    
    # Act
    result = parse_paper(pdf_path)
    
    # Assert
    assert result.title == "Attention Is All You Need"
    assert len(result.key_innovations) > 0
```

### Coverage

- **Minimum**: 80% for `paperforge/` package
- **Target**: 90% for critical paths (orchestrator, agents)
- **Run coverage**: `pytest --cov=paperforge --cov-report=html`

## 5. LLM Provider Configuration

PaperForge supports multiple LLM providers through an abstraction layer.

### Configuration via environment variables

```bash
# .env
LLM_PROVIDER=openai_compatible  # openai | anthropic | openai_compatible
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://chat-api.westaclab.com/v1
LLM_MODEL=glm-5.2
```

### Adding a new provider

1. Implement the `LLMClient` protocol in `paperforge/llm/`
2. Add the provider to the factory in `paperforge/llm/factory.py`
3. Add tests in `tests/unit/llm/`
4. Document in `docs/02-orchestrator.md`

## 6. Project Layout

```
PaperForge/
├── paperforge/                # Python package
│   ├── orchestrator/
│   │   ├── loop.py            # Main orchestrator loop
│   │   ├── tools.py           # Tool definitions and dispatch
│   │   └── events.py          # SSE event emitter
│   ├── agents/
│   │   ├── paper_parser.py    # PDF → capability card
│   │   ├── composer.py        # Multi-paper composition
│   │   ├── product_planner.py # PRD refinement (multi-turn)
│   │   ├── nextjs_generator.py # PRD → Next.js app
│   │   └── verifier.py        # App verification
│   ├── llm/
│   │   ├── base.py            # LLMClient protocol
│   │   ├── openai_provider.py
│   │   ├── anthropic_provider.py
│   │   └── factory.py
│   ├── sandbox/
│   │   ├── docker_runner.py   # Docker container management
│   │   └── monitor.py         # Background sandbox health check
│   ├── storage/
│   │   ├── db.py              # SQLite connection + schema
│   │   └── artifacts.py       # File-based artifact storage
│   ├── schemas/
│   │   ├── paper.py           # Paper, CapabilityCard
│   │   ├── composition.py
│   │   ├── prd.py
│   │   ├── app_manifest.py
│   │   └── verification.py
│   └── prompts/
│       ├── orchestrator.md
│       ├── paper_parser.md
│       ├── composer.md
│       ├── product_planner.md
│       ├── nextjs_generator.md
│       └── verifier.md
│
├── api/                       # FastAPI backend
│   ├── main.py
│   ├── deps.py
│   └── routes/
│       ├── runs.py
│       ├── messages.py
│       ├── events.py
│       ├── library.py
│       ├── sandboxes.py
│       ├── preview.py
│       ├── files.py
│       └── settings.py
│
├── web/                       # Next.js frontend
│   ├── app/
│   ├── components/
│   └── lib/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── data/                      # Runtime data (gitignored)
│   ├── paperforge.db
│   ├── library/
│   ├── generated_apps/
│   └── ...
│
└── docs/                      # Design documents
```

## 7. Design Rules

1. **自写 orchestrator**（不用 LangGraph）：一个 while loop 实现 agentic loop
2. **Sub-agent 即 tool**：每个 sub-agent 注册为 orchestrator 的 tool
3. **SSE 事件流**：前端通过 SSE 接收 orchestrator 事件
4. **SQLite 持久化**：元数据用 SQLite，大内容用文件
5. **多 Provider**：通过 `LLM_PROVIDER` env var 切换 LLM 后端
6. **Mock-first**：原型默认 mock 模型能力，真实集成需要手动编辑 adapter

## 8. PR Checklist

Before submitting a PR, ensure:

- [ ] Commits follow Conventional Commits
- [ ] `ruff check .` passes
- [ ] `ruff format --check .` passes
- [ ] `pytest tests/` passes
- [ ] New code has tests
- [ ] Public API has docstrings
- [ ] No secrets or API keys in code
- [ ] No `print()` statements (use `loguru` logger)

## 9. Common Commands

```bash
# Backend
python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd web && npm run dev

# Tests
pytest tests/
pytest tests/unit/test_paper_parser.py -v
pytest --cov=paperforge --cov-report=html

# Linting & formatting
ruff check .
ruff format .
mypy paperforge/

# Database
sqlite3 data/paperforge.db ".schema"

# Docker
docker pull node:20-alpine
docker ps
docker logs <container_id>
```

## 10. Debugging Tips

### Orchestrator loop issues

- Add logging in `paperforge/orchestrator/loop.py`
- Check SQLite `messages` table for conversation history
- Use `LLM_MOCK_MODE=true` to test without API calls

### Sandbox issues

- Verify Docker Desktop is running: `docker info`
- Check container logs: `docker logs <container_id>`
- Verify port allocation in `sandboxes` table
- Windows file watching: `WATCHPACK_POLLING=true` env var

### LLM API issues

- Verify API key in `.env`
- Check network connectivity
- Use `LLM_PROVIDER=openai` for OpenAI direct API
- Use `LLM_PROVIDER=openai_compatible` for Westlake/DeepSeek

## 11. Architecture Decision Records

Major architectural decisions are documented in `docs/`:

- `00-overview.md` — Overall architecture
- `01-project-structure.md` — Project layout decisions
- `02-orchestrator.md` — Orchestrator design (why not LangGraph)
- `03-sub-agents.md` — Sub-agent design (why 5 agents, not 10)
- `04-sandbox-preview.md` — Sandbox & preview design
- `05-frontend-ui.md` — Frontend UI design
- `06-backend-api.md` — Backend API design
- `07-data-model.md` — Data model & storage design
