# PaperForge

> 论文 → 可用产品 的自动化转化

PaperForge 是一个**论文产品化助手**。用户上传论文 PDF，系统通过多 agent 协作，生成可运行的 Next.js full-stack app，并在 Docker 沙箱中提供 live preview。

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+ and npm
- Docker Desktop (for sandbox preview)

### Installation

```bash
# Clone
git clone https://github.com/Vincent-Wenhan/PaperForge.git
cd PaperForge

# Backend setup
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -e ".[dev]"

# Environment
cp .env.example .env
# Edit .env to set your LLM API key

# Frontend setup
cd web
npm install
cd ..
```

### Running

```bash
# Terminal 1: Backend
python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Frontend
cd web
npm run dev
# Open http://localhost:3000
```

## Documentation

- `docs/00-overview.md` - Project overview
- `docs/01-project-structure.md` - Directory structure & design decisions
- `docs/02-orchestrator.md` - Orchestrator design (main loop, tools, SSE)
- `docs/03-sub-agents.md` - 5 sub-agents detailed design
- `docs/04-sandbox-preview.md` - Docker sandbox & live preview
- `docs/05-frontend-ui.md` - Next.js IDE-style UI
- `docs/06-backend-api.md` - FastAPI backend
- `docs/07-data-model.md` - SQLite schema & Storage class
- `docs/08-development.md` - Development conventions

## License

MIT
