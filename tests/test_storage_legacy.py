from __future__ import annotations

import sqlite3

from paperforge.storage.db import Storage


def test_legacy_messages_table_is_migrated(tmp_path):
    db_path = tmp_path / "legacy.db"
    data_dir = tmp_path / "data"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE runs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                tool_calls TEXT,
                tool_call_id TEXT,
                name TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    storage = Storage(db_path=db_path, data_dir=data_dir)

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}

    assert {"public_id", "status", "parts"} <= columns

    storage.create_run("run_legacy", "Legacy", status="active")
    message = storage.add_message("run_legacy", "user", "hello")
    assert message["public_id"].startswith("msg_")
    assert message["status"] == "completed"

