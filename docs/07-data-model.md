# PaperForge - Data Model & Storage Design

## 1. 存储层次

```
paperforge/
├── data/
│   ├── paperforge.db          # SQLite: runs, messages, sandboxes, papers
│   ├── library/               # 论文库(PDF + capability card)
│   │   ├── attention_2017.pdf
│   │   ├── attention_2017.json   # capability card
│   │   ├── vae_2013.pdf
│   │   └── vae_2013.json
│   ├── generated_apps/        # 生成的 Next.js apps
│   │   └── app_001/
│   │       ├── app/
│   │       ├── package.json
│   │       └── manifest.json
│   ├── compositions/          # 多论文组合结果
│   │   └── comp_001.json
│   ├── prds/                  # 产品需求文档
│   │   └── prd_001.json
│   └── verification_reports/  # 验证报告
│       └── verif_001.json
```

**设计原则**:
- **SQLite 存元数据**:runs、messages、sandboxes、papers 的索引
- **文件系统存大内容**:capability card、PRD、generated app
- **JSON 文件即 artifact**:每个 artifact 一个 JSON 文件,SQLite 存路径引用

## 2. SQLite Schema

```sql
-- Runs(一个 run = 一次会话)
CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active / completed / error
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_runs_updated ON runs(updated_at DESC);

-- Messages(对话历史)
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    role TEXT NOT NULL,          -- user / assistant / tool
    content TEXT NOT NULL,
    tool_calls TEXT,             -- JSON array, only for assistant with tool calls
    tool_call_id TEXT,           -- only for role=tool
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_messages_run ON messages(run_id, id);

-- Sandboxes(Docker 容器)
CREATE TABLE sandboxes (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
    container_id TEXT,
    app_path TEXT NOT NULL,
    preview_port INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending / running / stopped / error
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    stopped_at TIMESTAMP
);

CREATE INDEX idx_sandboxes_run ON sandboxes(run_id);
CREATE INDEX idx_sandboxes_status ON sandboxes(status);

-- Papers(论文库索引)
CREATE TABLE papers (
    paper_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    card_path TEXT,              -- capability card JSON 路径(解析后填入)
    status TEXT NOT NULL DEFAULT 'uploaded',  -- uploaded / parsed / error
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    parsed_at TIMESTAMP
);

CREATE INDEX idx_papers_status ON papers(status);

-- Artifacts(生成的产物索引)
CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
    type TEXT NOT NULL,          -- capability_card / composition / prd / nextjs_app / verification_report
    path TEXT NOT NULL,          -- 文件路径
    metadata TEXT,               -- JSON,额外元数据
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_artifacts_run ON artifacts(run_id);
CREATE INDEX idx_artifacts_type ON artifacts(type);
```

## 3. Storage 类

```python
# paperforge/storage/db.py

import sqlite3
from pathlib import Path
from typing import Any
import json
from contextlib import contextmanager


class Storage:
    def __init__(self, db_path: Path, data_dir: Path):
        self.db_path = db_path
        self.data_dir = data_dir
        self.library_dir = data_dir / "library"
        self.apps_dir = data_dir / "generated_apps"
        self.compositions_dir = data_dir / "compositions"
        self.prds_dir = data_dir / "prds"
        self.reports_dir = data_dir / "verification_reports"
        
        # 创建目录
        for d in [self.library_dir, self.apps_dir, self.compositions_dir, 
                  self.prds_dir, self.reports_dir]:
            d.mkdir(parents=True, exist_ok=True)
        
        # 初始化数据库
        self._init_db()
    
    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA_SQL)
    
    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    # === Runs ===
    
    def create_run(self, run: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO runs (id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (run["id"], run["title"], run["status"], run["created_at"], run["updated_at"]),
            )
    
    def get_run(self, run_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            return dict(row) if row else None
    
    def list_runs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]
    
    def update_run_status(self, run_id: str, status: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ?",
                (status, datetime.utcnow(), run_id),
            )
    
    def delete_run(self, run_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
    
    # === Messages ===
    
    def add_message(self, run_id: str, message: dict) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO messages (run_id, role, content, tool_calls, tool_call_id) VALUES (?, ?, ?, ?, ?)",
                (run_id, message["role"], message["content"], 
                 message.get("tool_calls_json"), message.get("tool_call_id")),
            )
            return cur.lastrowid
    
    def list_messages(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
    
    # === Sandboxes ===
    
    def save_sandbox(self, sandbox: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO sandboxes (id, run_id, container_id, app_path, preview_port, status, created_at, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (sandbox["id"], sandbox["run_id"], sandbox["container_id"], 
                 sandbox["app_path"], sandbox["preview_port"], sandbox["status"],
                 sandbox["created_at"], sandbox.get("started_at")),
            )
    
    def get_sandbox(self, sandbox_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM sandboxes WHERE id = ?", (sandbox_id,)
            ).fetchone()
            return dict(row) if row else None
    
    def update_sandbox(self, sandbox_id: str, **kwargs) -> None:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE sandboxes SET {sets} WHERE id = ?",
                (*kwargs.values(), sandbox_id),
            )
    
    def list_sandboxes(self, status: str | None = None) -> list[dict]:
        query = "SELECT * FROM sandboxes"
        params = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
    
    def delete_sandbox(self, sandbox_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sandboxes WHERE id = ?", (sandbox_id,))
    
    # === Papers ===
    
    def upsert_paper(self, paper: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO papers (paper_id, title, pdf_path, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                    title = excluded.title,
                    pdf_path = excluded.pdf_path,
                    status = excluded.status""",
                (paper["paper_id"], paper["title"], paper["pdf_path"], 
                 paper["status"], paper.get("created_at", datetime.utcnow())),
            )
    
    def get_paper(self, paper_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE paper_id = ?", (paper_id,)
            ).fetchone()
            return dict(row) if row else None
    
    def list_papers(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM papers ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
    
    def delete_paper(self, paper_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM papers WHERE paper_id = ?", (paper_id,))
    
    # === Artifacts ===
    
    def save_artifact(self, run_id: str, artifact_type: str, data: dict) -> str:
        artifact_id = f"{artifact_type}_{uuid.uuid4().hex[:8]}"
        path = self._get_artifact_path(artifact_type, artifact_id)
        
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO artifacts (id, run_id, type, path, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (artifact_id, run_id, artifact_type, str(path), 
                 json.dumps({"type": artifact_type}), datetime.utcnow()),
            )
        
        return artifact_id
    
    def get_artifact(self, artifact_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
            if not row:
                return None
            path = Path(row["path"])
            if not path.exists():
                return None
            return {
                "id": row["id"],
                "run_id": row["run_id"],
                "type": row["type"],
                "path": row["path"],
                "metadata": json.loads(row["metadata"] or "{}"),
                "data": json.loads(path.read_text()),
            }
    
    def list_artifacts(self, run_id: str, artifact_type: str | None = None) -> list[dict]:
        query = "SELECT * FROM artifacts WHERE run_id = ?"
        params = (run_id,)
        if artifact_type:
            query += " AND type = ?"
            params = (run_id, artifact_type)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
    
    def _get_artifact_path(self, artifact_type: str, artifact_id: str) -> Path:
        mapping = {
            "capability_card": self.library_dir,  # cards 跟论文一起存
            "composition": self.compositions_dir,
            "prd": self.prds_dir,
            "verification_report": self.reports_dir,
        }
        return mapping.get(artifact_type, self.data_dir) / f"{artifact_id}.json"
```

## 4. 数据访问模式

**读路径(前端请求 run 详情)**:
```
GET /api/runs/run_abc123
  → storage.get_run("run_abc123")
  → 返回 run 元数据

GET /api/runs/run_abc123/messages
  → storage.list_messages("run_abc123")
  → 返回消息列表

GET /api/runs/run_abc123/artifacts?type=capability_card
  → storage.list_artifacts("run_abc123", "capability_card")
  → 返回该 run 下所有 capability card artifacts
```

**写路径(orchestrator 执行 tool)**:
```
orchestrator.run() → handle_parse_paper()
  → paper_parser.run(pdf_path, paper_id)
  → 在 library/ 下生成 attention_2017.json
  → storage.save_artifact(run_id, "capability_card", card_data)
  → 返回 artifact_id 给 orchestrator
```

## 5. 数据一致性

**事务边界**:
- `create_run` 是一个事务
- `add_message` 是一个事务
- `save_artifact` 跨文件系统和数据库,不保证原子性

**失败恢复**:
- orchestrator 失败 → run 状态保持 active,前端 SSE 断开
- sandbox 失败 → sandbox 状态变 error,run 继续
- 文件写入失败 → tool 返回 error,orchestrator 决定下一步

## 6. 数据迁移

```python
# paperforge/storage/migrations.py

MIGRATIONS = [
    # V1: 初始 schema
    """
    CREATE TABLE IF NOT EXISTS runs (...);
    CREATE TABLE IF NOT EXISTS messages (...);
    ...
    """,
    # V2: 添加 papers 表
    """
    CREATE TABLE IF NOT EXISTS papers (...);
    """,
    # 后续迁移...
]


def migrate(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER)")
    version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
    
    for i, migration in enumerate(MIGRATIONS[version:], start=version+1):
        conn.executescript(migration)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (i,))
        conn.commit()
    
    conn.close()
```

## 7. 备份与清理

**备份**:
- `data/paperforge.db` 是 SQLite 文件,直接复制即可备份
- `data/library/` 和 `data/generated_apps/` 是文件,直接打包

**清理**:
- 超过 30 天的 completed runs 可清理
- 失败的 sandboxes 24 小时后清理
- 没有论文引用的 capability cards 可清理

## 8. 关键决策

1. **SQLite + 文件系统混合存储**:元数据用 SQLite,大内容用文件
2. **每个 artifact 一个 JSON 文件**:易调试、易备份、易迁移
3. **WAL 模式**:多读单写,适合 SSE 场景
4. **路径引用**:SQLite 存路径,文件系统存内容
5. **数据一致性**:不保证跨存储原子性,通过状态机管理

---

## 9. 数据模型总结

| 实体 | 存储 | 说明 |
|---|---|---|
| Run | SQLite | 一次会话 |
| Message | SQLite | 对话历史 |
| Sandbox | SQLite + 文件系统 | Docker 容器 + 生成的 app 文件 |
| Paper | SQLite + 文件系统 | 论文索引 + PDF + capability card |
| Artifact | SQLite + 文件系统 | 产物索引 + JSON 文件 |
| Composition | Artifact | 多论文组合结果 |
| PRD | Artifact | 产品需求文档 |
| VerificationReport | Artifact | 验证报告 |
