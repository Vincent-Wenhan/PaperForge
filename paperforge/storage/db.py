"""SQLite storage layer + schema initialization."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from paperforge.config import get_config


SCHEMA_SQL_TABLES = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    phase TEXT NOT NULL DEFAULT 'init',
    pinned INTEGER NOT NULL DEFAULT 0,
    archived_at TIMESTAMP,
    last_message_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT,
    tool_calls TEXT,
    tool_call_id TEXT,
    name TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sandboxes (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
    container_id TEXT,
    app_path TEXT NOT NULL,
    preview_port INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    stopped_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    card_path TEXT,
    status TEXT NOT NULL DEFAULT 'uploaded',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    parsed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    path TEXT NOT NULL,
    metadata TEXT,
    display_name TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    parent_artifact_id TEXT,
    updated_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    args TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    resolved_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS run_papers (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    paper_id TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
    attached_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, paper_id)
);

CREATE TABLE IF NOT EXISTS run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    task_id TEXT,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    data TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    title TEXT,
    goal TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    phase TEXT NOT NULL DEFAULT 'init',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);
"""

SCHEMA_SQL_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_runs_updated ON runs(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_archived ON runs(archived_at);
CREATE INDEX IF NOT EXISTS idx_messages_run ON messages(run_id, id);
CREATE INDEX IF NOT EXISTS idx_sandboxes_run ON sandboxes(run_id);
CREATE INDEX IF NOT EXISTS idx_sandboxes_status ON sandboxes(status);
CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(type);
CREATE INDEX IF NOT EXISTS idx_run_events ON run_events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_tasks_run ON tasks(run_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""

# Kept for compatibility; new init uses SCHEMA_SQL_TABLES + SCHEMA_SQL_INDEXES.
SCHEMA_SQL = SCHEMA_SQL_TABLES + SCHEMA_SQL_INDEXES


class Storage:
    """Thread-safe SQLite + filesystem storage."""

    def __init__(self, db_path: Path, data_dir: Path) -> None:
        self.db_path = Path(db_path)
        self.data_dir = Path(data_dir)
        self.library_dir = self.data_dir / "library"
        self.apps_dir = self.data_dir / "generated_apps"
        self.compositions_dir = self.data_dir / "compositions"
        self.prds_dir = self.data_dir / "prds"
        self.reports_dir = self.data_dir / "verification_reports"
        self.uploads_dir = self.data_dir / "uploads"

        for d in [
            self.data_dir,
            self.library_dir,
            self.apps_dir,
            self.compositions_dir,
            self.prds_dir,
            self.reports_dir,
            self.uploads_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._conn() as conn:
            # Step 1: Create tables (without indexes that may reference
            # columns missing in older databases).
            conn.executescript(SCHEMA_SQL_TABLES)
            # Step 2: Migrations - add columns that older databases may be missing.
            self._ensure_column(conn, "runs", "phase", "TEXT DEFAULT 'init'")
            self._ensure_column(conn, "runs", "pinned", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "runs", "archived_at", "TIMESTAMP")
            self._ensure_column(conn, "runs", "last_message_at", "TIMESTAMP")
            # Step 3: Create indexes (now that all columns exist).
            conn.executescript(SCHEMA_SQL_INDEXES)
    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        table: str,
        column: str,
        decl: str,
    ) -> None:
        try:
            conn.execute(f"SELECT {column} FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # ===== Runs =====

    def create_run(self, run_id: str, title: str, status: str = "active") -> dict[str, Any]:
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO runs (id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, title, status, now, now),
            )
        return {"id": run_id, "title": title, "status": status, "created_at": now, "updated_at": now}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            return dict(row) if row else None

    def list_runs(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_run_status(self, run_id: str, status: str) -> None:
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, run_id),
            )

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
            return row["phase"] if row and row["phase"] else "init"

    def get_run_status(self, run_id: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT status FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            return row["status"] if row else None

    def touch_run(self, run_id: str) -> None:
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE runs SET updated_at = ? WHERE id = ?", (now, run_id))

    def delete_run(self, run_id: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))

    def update_run(
        self,
        run_id: str,
        title: str | None = None,
        pinned: bool | None = None,
    ) -> dict[str, Any] | None:
        sets: list[str] = []
        params: list[Any] = []
        if title is not None:
            sets.append("title = ?")
            params.append(title)
        if pinned is not None:
            sets.append("pinned = ?")
            params.append(1 if pinned else 0)
        if not sets:
            return self.get_run(run_id)
        sets.append("updated_at = ?")
        params.append(datetime.utcnow().isoformat())
        params.append(run_id)
        with self._lock, self._conn() as conn:
            conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id = ?", params)
        return self.get_run(run_id)

    def archive_run(self, run_id: str) -> dict[str, Any] | None:
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE runs SET archived_at = ?, updated_at = ? WHERE id = ?",
                (now, now, run_id),
            )
        return self.get_run(run_id)

    def restore_run(self, run_id: str) -> dict[str, Any] | None:
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE runs SET archived_at = NULL, updated_at = ? WHERE id = ?",
                (now, run_id),
            )
        return self.get_run(run_id)

    # ===== Messages =====

    def add_message(
        self,
        run_id: str,
        role: str,
        content: str | None = None,
        tool_calls: list[dict] | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
    ) -> int:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO messages (run_id, role, content, tool_calls, tool_call_id, name)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    role,
                    content,
                    json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                    tool_call_id,
                    name,
                ),
            )
            return cur.lastrowid

    def list_messages(self, run_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("tool_calls"):
                d["tool_calls"] = json.loads(d["tool_calls"])
            result.append(d)
        return result

    # ===== Sandboxes =====

    def save_sandbox(
        self,
        sandbox_id: str,
        run_id: str,
        app_path: str,
        container_id: str | None = None,
        preview_port: int | None = None,
        status: str = "pending",
    ) -> dict[str, Any]:
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO sandboxes (id, run_id, container_id, app_path, preview_port, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (sandbox_id, run_id, container_id, app_path, preview_port, status, now),
            )
        return {
            "id": sandbox_id,
            "run_id": run_id,
            "container_id": container_id,
            "app_path": app_path,
            "preview_port": preview_port,
            "status": status,
            "created_at": now,
        }

    def get_sandbox(self, sandbox_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM sandboxes WHERE id = ?", (sandbox_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_latest_sandbox_for_run(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM sandboxes WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None

    # ===== Tasks =====

    def create_task(
        self,
        run_id: str,
        title: str | None = None,
        goal: str | None = None,
        status: str = "queued",
        phase: str = "init",
    ) -> dict[str, Any]:
        now = datetime.utcnow().isoformat()
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO tasks (id, run_id, title, goal, status, phase, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_id, run_id, title, goal, status, phase, now, now),
            )
        return {
            "id": task_id,
            "run_id": run_id,
            "title": title,
            "goal": goal,
            "status": status,
            "phase": phase,
            "created_at": now,
            "updated_at": now,
        }

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_tasks(self, run_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE run_id = ? ORDER BY created_at DESC",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_task(
        self,
        task_id: str,
        title: str | None = None,
        status: str | None = None,
        phase: str | None = None,
        goal: str | None = None,
    ) -> dict[str, Any] | None:
        sets: list[str] = []
        params: list[Any] = []
        if title is not None:
            sets.append("title = ?")
            params.append(title)
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if phase is not None:
            sets.append("phase = ?")
            params.append(phase)
        if goal is not None:
            sets.append("goal = ?")
            params.append(goal)
        if not sets:
            return self.get_task(task_id)
        sets.append("updated_at = ?")
        params.append(datetime.utcnow().isoformat())
        params.append(task_id)
        with self._lock, self._conn() as conn:
            conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", params)
        return self.get_task(task_id)

    def delete_task(self, task_id: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def list_sandboxes(self, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM sandboxes"
        params: tuple[Any, ...] = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def update_sandbox(self, sandbox_id: str, **kwargs: Any) -> None:
        if not kwargs:
            return
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        with self._lock, self._conn() as conn:
            conn.execute(
                f"UPDATE sandboxes SET {sets} WHERE id = ?",
                (*kwargs.values(), sandbox_id),
            )

    def delete_sandbox(self, sandbox_id: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM sandboxes WHERE id = ?", (sandbox_id,))

    # ===== Papers =====

    def upsert_paper(
        self,
        paper_id: str,
        title: str,
        pdf_path: str,
        status: str = "uploaded",
        card_path: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO papers (paper_id, title, pdf_path, card_path, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(paper_id) DO UPDATE SET
                       title = excluded.title,
                       pdf_path = excluded.pdf_path,
                       card_path = excluded.card_path,
                       status = excluded.status""",
                (paper_id, title, pdf_path, card_path, status, now),
            )
        return {
            "paper_id": paper_id,
            "title": title,
            "pdf_path": pdf_path,
            "card_path": card_path,
            "status": status,
            "created_at": now,
        }

    def get_paper(self, paper_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE paper_id = ?", (paper_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_papers(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM papers ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_paper_status(self, paper_id: str, status: str, card_path: str | None = None) -> None:
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            if card_path:
                conn.execute(
                    "UPDATE papers SET status = ?, card_path = ?, parsed_at = ? WHERE paper_id = ?",
                    (status, card_path, now, paper_id),
                )
            else:
                conn.execute(
                    "UPDATE papers SET status = ?, parsed_at = ? WHERE paper_id = ?",
                    (status, now, paper_id),
                )

    def update_paper_title(self, paper_id: str, title: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE papers SET title = ? WHERE paper_id = ?",
                (title, paper_id),
            )

    def delete_paper(self, paper_id: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM papers WHERE paper_id = ?", (paper_id,))

    # ===== Artifacts =====

    def save_artifact(
        self,
        run_id: str,
        artifact_type: str,
        data: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        artifact_id = f"{artifact_type}_{uuid.uuid4().hex[:8]}"
        path = self._artifact_path(artifact_type, artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO artifacts
                   (id, run_id, type, path, metadata, version, updated_at, created_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    artifact_id,
                    run_id,
                    artifact_type,
                    str(path),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return artifact_id

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            path = Path(d["path"])
            if path.exists():
                d["data"] = json.loads(path.read_text(encoding="utf-8"))
            d["metadata"] = json.loads(d.get("metadata") or "{}")
            return d

    def list_artifacts(
        self, run_id: str | None = None, artifact_type: str | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM artifacts WHERE 1=1"
        params: list[Any] = []
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        if artifact_type:
            query += " AND type = ?"
            params.append(artifact_type)
        query += " ORDER BY created_at DESC"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def _artifact_path(self, artifact_type: str, artifact_id: str) -> Path:
        mapping = {
            "capability_card": self.library_dir,
            "composition": self.compositions_dir,
            "prd": self.prds_dir,
            "verification_report": self.reports_dir,
            "nextjs_app": self.apps_dir,
        }
        return mapping.get(artifact_type, self.data_dir) / f"{artifact_id}.json"

    # ===== Approvals =====

    def create_approval(
        self, run_id: str, tool_name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        approval_id = f"apv_{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO approvals (id, run_id, tool_name, args, status, created_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)""",
                (
                    approval_id,
                    run_id,
                    tool_name,
                    json.dumps(args, ensure_ascii=False),
                    now,
                ),
            )
        return {
            "id": approval_id,
            "run_id": run_id,
            "tool_name": tool_name,
            "args": args,
            "status": "pending",
            "created_at": now,
        }

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["args"] = json.loads(d.get("args") or "{}")
            return d

    def resolve_approval(self, approval_id: str, approved: bool) -> None:
        now = datetime.utcnow().isoformat()
        status = "approved" if approved else "rejected"
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE approvals SET status = ?, resolved_at = ? WHERE id = ?",
                (status, now, approval_id),
            )

    def list_approvals(
        self,
        run_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List approvals, optionally filtered by run_id and/or status."""
        query = "SELECT * FROM approvals WHERE 1=1"
        params: list[Any] = []
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["args"] = json.loads(d.get("args") or "{}")
                out.append(d)
            return out

    # ===== Run-Paper attachments =====

    def attach_paper_to_run(self, run_id: str, paper_id: str) -> dict[str, Any]:
        """Attach a paper to a run. Idempotent."""
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO run_papers (run_id, paper_id, attached_at)
                   VALUES (?, ?, ?)""",
                (run_id, paper_id, now),
            )
        return {"run_id": run_id, "paper_id": paper_id, "attached_at": now}

    def detach_paper_from_run(self, run_id: str, paper_id: str) -> bool:
        """Detach a paper from a run. Returns True if a row was deleted."""
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM run_papers WHERE run_id = ? AND paper_id = ?",
                (run_id, paper_id),
            )
            return cur.rowcount > 0

    def list_run_papers(self, run_id: str) -> list[dict[str, Any]]:
        """List papers attached to a run."""
        query = """
            SELECT p.* FROM papers p
            JOIN run_papers rp ON rp.paper_id = p.paper_id
            WHERE rp.run_id = ?
            ORDER BY rp.attached_at DESC
        """
        with self._conn() as conn:
            rows = conn.execute(query, (run_id,)).fetchall()
            return [dict(r) for r in rows]

    # ===== Run event persistence (doc 11) =====

    def save_run_event(
        self,
        run_id: str,
        event_id: str,
        seq: int,
        type: str,
        data: Any,
        task_id: str | None = None,
    ) -> None:
        """Persist a single run event for replay after backend restart."""
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO run_events (id, run_id, task_id, seq, type, data, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    run_id,
                    task_id,
                    seq,
                    type,
                    json.dumps(data, ensure_ascii=False) if data is not None else None,
                    datetime.utcnow().isoformat(),
                ),
            )

    def list_run_events(
        self,
        run_id: str,
        after_seq: int = 0,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Return persisted events for a run with seq > after_seq."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM run_events
                   WHERE run_id = ? AND seq > ?
                   ORDER BY seq ASC
                   LIMIT ?""",
                (run_id, after_seq, limit),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                if d.get("data"):
                    try:
                        d["data"] = json.loads(d["data"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                out.append(d)
            return out


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        cfg = get_config()
        _storage = Storage(db_path=cfg.DB_PATH, data_dir=cfg.DATA_DIR)
    return _storage


def reset_storage() -> None:
    global _storage
    _storage = None


def init_db(db_path: Path | None = None) -> None:
    """Initialize the database schema. Uses config DB_PATH unless override given."""
    if db_path is None:
        cfg = get_config()
        db_path = cfg.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage = Storage(db_path=db_path, data_dir=db_path.parent)
    _ = storage  # already initializes schema in __init__
