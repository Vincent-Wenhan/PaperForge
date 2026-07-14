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
    public_id TEXT UNIQUE,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT,
    tool_calls TEXT,
    tool_call_id TEXT,
    name TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    parts TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sandboxes (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
    container_id TEXT,
    app_path TEXT NOT NULL,
    preview_port INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    preview_status TEXT NOT NULL DEFAULT 'idle',
    preview_url TEXT,
    error TEXT,
    environment TEXT NOT NULL DEFAULT 'docker',
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

CREATE TABLE IF NOT EXISTS workspace_revisions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    app_id TEXT NOT NULL,
    parent_revision_id TEXT,
    source TEXT NOT NULL,
    changed_files TEXT NOT NULL,
    snapshot_path TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
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
CREATE UNIQUE INDEX IF NOT EXISTS uq_run_events_run_seq
    ON run_events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_tasks_run ON tasks(run_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_workspace_revisions_app
    ON workspace_revisions(app_id, created_at DESC);
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
        self.workspace_revisions_dir = self.data_dir / "workspace_revisions"

        for d in [
            self.data_dir,
            self.library_dir,
            self.apps_dir,
            self.compositions_dir,
            self.prds_dir,
            self.reports_dir,
            self.uploads_dir,
            self.workspace_revisions_dir,
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
            self._ensure_column(conn, "messages", "public_id", "TEXT")
            self._ensure_column(conn, "messages", "status", "TEXT NOT NULL DEFAULT 'completed'")
            self._ensure_column(conn, "messages", "parts", "TEXT")
            self._ensure_column(conn, "sandboxes", "preview_status", "TEXT NOT NULL DEFAULT 'idle'")
            self._ensure_column(conn, "sandboxes", "preview_url", "TEXT")
            self._ensure_column(conn, "sandboxes", "error", "TEXT")
            self._ensure_column(conn, "sandboxes", "environment", "TEXT NOT NULL DEFAULT 'docker'")
            conn.execute(
                "UPDATE sandboxes SET preview_status = 'starting' "
                "WHERE preview_status = 'idle' AND status IN ('pending', 'starting', 'running')"
            )
            conn.execute(
                "UPDATE sandboxes SET preview_status = 'stopped' "
                "WHERE preview_status = 'idle' AND status = 'stopped'"
            )
            conn.execute(
                "UPDATE sandboxes SET preview_status = 'degraded' "
                "WHERE preview_status = 'idle' AND status IN ('error', 'failed')"
            )
            # Older databases predate public_id. Backfill deterministically
            # before creating the unique index used by new writes.
            conn.execute(
                "UPDATE messages SET public_id = 'msg_legacy_' || id "
                "WHERE public_id IS NULL OR public_id = ''"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_public_id "
                "ON messages(public_id)"
            )
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
        public_id: str | None = None,
        status: str = "completed",
        parts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if public_id is None:
            public_id = f"msg_{uuid.uuid4().hex[:10]}"
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO messages
                   (public_id, run_id, role, content, tool_calls, tool_call_id, name, status, parts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    public_id,
                    run_id,
                    role,
                    content,
                    json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                    tool_call_id,
                    name,
                    status,
                    json.dumps(parts, ensure_ascii=False) if parts else None,
                ),
            )
            now = datetime.utcnow().isoformat()
            conn.execute(
                "UPDATE runs SET last_message_at = ?, updated_at = ? WHERE id = ?",
                (now, now, run_id),
            )
            row = conn.execute(
                "SELECT * FROM messages WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
        return dict(row)

    def update_message(
        self,
        public_id: str,
        *,
        content: str | None = None,
        status: str | None = None,
        tool_calls: list[dict] | None = None,
        parts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Update a durable message by its public streaming ID."""
        sets: list[str] = []
        params: list[Any] = []
        if content is not None:
            sets.append("content = ?")
            params.append(content)
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if tool_calls is not None:
            sets.append("tool_calls = ?")
            params.append(json.dumps(tool_calls, ensure_ascii=False))
        if parts is not None:
            sets.append("parts = ?")
            params.append(json.dumps(parts, ensure_ascii=False))
        if not sets:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM messages WHERE public_id = ?", (public_id,)
                ).fetchone()
            return dict(row) if row else None

        params.append(public_id)
        with self._lock, self._conn() as conn:
            conn.execute(
                f"UPDATE messages SET {', '.join(sets)} WHERE public_id = ?",
                params,
            )
            row = conn.execute(
                "SELECT * FROM messages WHERE public_id = ?", (public_id,)
            ).fetchone()
        return dict(row) if row else None

    def create_streaming_message(self, run_id: str, public_id: str) -> dict[str, Any]:
        """Create the assistant row before the first SSE delta is emitted."""
        return self.add_message(
            run_id=run_id,
            role="assistant",
            content="",
            public_id=public_id,
            status="streaming",
        )

    def append_message_delta(self, public_id: str, delta: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE messages SET content = COALESCE(content, '') || ? WHERE public_id = ?",
                (delta, public_id),
            )

    def complete_message(
        self,
        public_id: str,
        content: str,
        tool_calls: list[dict] | None = None,
    ) -> dict[str, Any] | None:
        return self.update_message(
            public_id,
            content=content,
            status="completed",
            tool_calls=tool_calls,
        )

    def fail_message(self, public_id: str, error: str) -> dict[str, Any] | None:
        return self.update_message(public_id, content=error, status="failed")

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
            if d.get("parts"):
                d["parts"] = json.loads(d["parts"])
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
        preview_status: str = "idle",
        preview_url: str | None = None,
        error: str | None = None,
        environment: str = "docker",
    ) -> dict[str, Any]:
        if preview_status == "idle":
            preview_status = {
                "running": "running",
                "pending": "starting",
                "starting": "starting",
                "error": "degraded",
                "failed": "degraded",
                "stopped": "stopped",
            }.get(status, "idle")
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO sandboxes
                   (id, run_id, container_id, app_path, preview_port, status,
                    preview_status, preview_url, error, environment, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sandbox_id,
                    run_id,
                    container_id,
                    app_path,
                    preview_port,
                    status,
                    preview_status,
                    preview_url,
                    error,
                    environment,
                    now,
                ),
            )
        return {
            "id": sandbox_id,
            "run_id": run_id,
            "container_id": container_id,
            "app_path": app_path,
            "preview_port": preview_port,
            "status": status,
            "preview_status": preview_status,
            "preview_url": preview_url,
            "error": error,
            "environment": environment,
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
            if status in {"completed", "failed", "cancelled"}:
                sets.append("completed_at = ?")
                params.insert(-1, datetime.utcnow().isoformat())
            conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", params)
        return self.get_task(task_id)

    def delete_task(self, task_id: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    # ===== Workspace revisions =====

    def _snapshot_workspace(self, app_path: Path) -> dict[str, str]:
        blocked = {"node_modules", ".next", ".git", "dist", "build", ".cache"}
        snapshot: dict[str, str] = {}
        if not app_path.exists():
            return snapshot
        for path in app_path.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(app_path).parts
            if any(part in blocked for part in rel) or path.stat().st_size > 1_000_000:
                continue
            try:
                snapshot["/".join(rel)] = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
        return snapshot

    def create_workspace_revision(
        self,
        run_id: str,
        app_id: str,
        source: str,
        app_path: str | Path,
        parent_revision_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist a bounded source snapshot and its changed-file list."""
        current = self._snapshot_workspace(Path(app_path).resolve())
        if parent_revision_id is None:
            previous = self.list_workspace_revisions(app_id)
            parent_revision_id = previous[0]["id"] if previous else None
        parent_snapshot: dict[str, str] = {}
        if parent_revision_id:
            parent = self.get_workspace_revision(parent_revision_id, include_snapshot=True)
            parent_snapshot = (parent or {}).get("snapshot") or {}

        changed_files = sorted(
            path
            for path in set(current) | set(parent_snapshot)
            if current.get(path) != parent_snapshot.get(path)
        )
        revision_id = f"rev_{uuid.uuid4().hex[:10]}"
        snapshot_path = self.workspace_revisions_dir / f"{revision_id}.json"
        snapshot_path.write_text(
            json.dumps(current, ensure_ascii=False),
            encoding="utf-8",
        )
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO workspace_revisions
                   (id, run_id, app_id, parent_revision_id, source,
                    changed_files, snapshot_path, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    revision_id,
                    run_id,
                    app_id,
                    parent_revision_id,
                    source,
                    json.dumps(changed_files, ensure_ascii=False),
                    str(snapshot_path),
                    now,
                ),
            )
        return {
            "id": revision_id,
            "revision_id": revision_id,
            "run_id": run_id,
            "app_id": app_id,
            "parent_revision_id": parent_revision_id,
            "source": source,
            "changed_files": changed_files,
            "created_at": now,
        }

    def list_workspace_revisions(self, app_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM workspace_revisions WHERE app_id = "
                "? ORDER BY created_at DESC",
                (app_id,),
            ).fetchall()
        return [self._decode_workspace_revision(dict(row)) for row in rows]

    def get_workspace_revision(
        self,
        revision_id: str,
        *,
        include_snapshot: bool = False,
    ) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM workspace_revisions WHERE id = ?",
                (revision_id,),
            ).fetchone()
        if not row:
            return None
        revision = self._decode_workspace_revision(dict(row))
        if include_snapshot:
            path = Path(revision["snapshot_path"])
            if path.exists():
                try:
                    revision["snapshot"] = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    revision["snapshot"] = {}
        return revision

    def restore_workspace_revision(
        self,
        revision_id: str,
        app_path: str | Path,
    ) -> dict[str, Any] | None:
        """Restore a stored workspace snapshot to its app directory.

        The caller is responsible for validating artifact/run ownership. This
        method only applies the bounded snapshot and never touches blocked
        dependency/build directories.
        """
        revision = self.get_workspace_revision(revision_id, include_snapshot=True)
        if not revision:
            return None
        snapshot = revision.get("snapshot") or {}
        base = Path(app_path).resolve()
        blocked = {"node_modules", ".next", ".git", "dist", "build", ".cache"}

        for path in base.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(base).parts
            if any(part in blocked for part in relative):
                continue
            relative_key = "/".join(relative)
            if relative_key not in snapshot:
                path.unlink()

        for relative_key, content in snapshot.items():
            target = (base / relative_key).resolve()
            try:
                target.relative_to(base)
            except (ValueError, RuntimeError) as exc:
                raise ValueError("Workspace snapshot contains an unsafe path") from exc
            if any(part in blocked for part in target.relative_to(base).parts):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
        return revision

    @staticmethod
    def _decode_workspace_revision(row: dict[str, Any]) -> dict[str, Any]:
        row["revision_id"] = row["id"]
        row["changed_files"] = json.loads(row.get("changed_files") or "[]")
        return row

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

    def update_artifact(
        self,
        artifact_id: str,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Update an artifact payload and/or metadata in place.

        Verification reports are created before a sandbox starts and receive
        runtime/acceptance results afterwards. Keeping the same artifact ID
        makes the report durable and lets the UI refresh it without creating
        duplicate report cards.
        """
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            return None

        path = Path(artifact["path"])
        now = datetime.utcnow().isoformat()
        next_metadata = artifact.get("metadata") or {}
        if metadata is not None:
            next_metadata = {**next_metadata, **metadata}
        if data is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE artifacts SET metadata = ?, version = version + 1, updated_at = ? "
                "WHERE id = ?",
                (json.dumps(next_metadata, ensure_ascii=False), now, artifact_id),
            )
        return self.get_artifact(artifact_id)

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

    def resolve_approval(self, approval_id: str, approved: bool) -> dict[str, Any] | None:
        now = datetime.utcnow().isoformat()
        status = "approved" if approved else "rejected"
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "UPDATE approvals SET status = ?, resolved_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (status, now, approval_id),
            )
            if cur.rowcount == 0:
                return None
        return self.get_approval(approval_id)

    def expire_approval(self, approval_id: str) -> dict[str, Any] | None:
        """Expire an unresolved approval after its bounded wait window."""
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE approvals SET status = 'expired', resolved_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (now, approval_id),
            )
        return self.get_approval(approval_id)

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

    def append_run_event(
        self,
        *,
        run_id: str,
        event_id: str,
        event_type: str,
        data: Any,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Append a run event with DB-assigned monotonic seq.

        Uses BEGIN IMMEDIATE to serialize concurrent appenders so that
        each event gets a unique per-run seq even under contention.
        """
        now = datetime.utcnow().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM run_events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                seq = int(row["max_seq"]) + 1
                conn.execute(
                    """INSERT INTO run_events
                       (id, run_id, task_id, seq, type, data, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event_id,
                        run_id,
                        task_id,
                        seq,
                        event_type,
                        json.dumps(data, ensure_ascii=False) if data is not None else None,
                        now,
                    ),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {
            "id": event_id,
            "run_id": run_id,
            "task_id": task_id,
            "seq": seq,
            "type": event_type,
            "data": data,
            "created_at": now,
        }

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

    def get_max_event_seq(self, run_id: str) -> int:
        """Return the highest seq for a run, or 0 if no events."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM run_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return int(row["max_seq"])

    def list_run_events(
        self,
        run_id: str,
        after_seq: int = 0,
        limit: int = 1000,
        up_to_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return persisted events for a run with seq > after_seq.

        If ``up_to_seq`` is given, only events with seq <= up_to_seq are
        returned. This lets an SSE route snapshot the DB upper bound
        before subscribing to live events, then replay everything up to
        that bound without race.
        """
        query = """SELECT * FROM run_events
                   WHERE run_id = ? AND seq > ?"""
        params: list[Any] = [run_id, after_seq]
        if up_to_seq is not None:
            query += " AND seq <= ?"
            params.append(up_to_seq)
        query += " ORDER BY seq ASC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
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
