"""
Plain sqlite3 (no SQLAlchemy). Two things live here:

* `runs`    - the existing scan-pipeline history (zip upload -> report files).
* `sessions`/`messages`/`workspaces` - the chat agent's durable state, so a
  redeploy or a Render free-tier spin-down does not erase a conversation.

Connections are opened per call (cheap for SQLite) with WAL enabled so the
chat thread and the scan pipeline do not fight over a write lock.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    app_name TEXT,
    framework TEXT,
    verdict TEXT,
    high_count INTEGER,
    medium_count INTEGER,
    low_count INTEGER,
    files_scanned INTEGER,
    files_llm_reviewed INTEGER,
    md_path TEXT,
    html_path TEXT,
    report_json TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    workspace_root TEXT,
    allow_edits INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    tool_name TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS workspaces (
    path TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
"""


def _db_path() -> Path:
    return Path(settings.database_path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA_READY = False


def _ensure_schema(conn):
    global _SCHEMA_READY
    if not _SCHEMA_READY:
        conn.executescript(SCHEMA)
        _SCHEMA_READY = True


@contextmanager
def get_conn():
    conn = sqlite3.connect(_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    _ensure_schema(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# --- scan pipeline -----------------------------------------------------------

def save_run(report, md_path: str, html_path: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, created_at, app_name, framework, verdict, high_count, medium_count,
                low_count, files_scanned, files_llm_reviewed, md_path, html_path, report_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.run_id, report.created_at, report.detected_environment.app_name,
                report.detected_environment.framework, report.verdict,
                report.counts.get("HIGH", 0), report.counts.get("MEDIUM", 0), report.counts.get("LOW", 0),
                report.total_files_scanned, report.total_files_llm_reviewed,
                md_path, html_path, report.model_dump_json(),
            ),
        )


def list_runs(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT run_id, created_at, app_name, framework, verdict, high_count, medium_count,
                      low_count, files_scanned, files_llm_reviewed
               FROM runs ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_run(run_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["report"] = json.loads(d.pop("report_json"))
        return d


# --- workspaces --------------------------------------------------------------

def register_workspace(path: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO workspaces (path, created_at) VALUES (?, ?)",
            (path, _now()),
        )


def is_registered_workspace(path: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM workspaces WHERE path = ?", (path,)).fetchone()
        return row is not None


def list_workspaces() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT path FROM workspaces ORDER BY created_at DESC").fetchall()
        return [r["path"] for r in rows]


# --- chat sessions -----------------------------------------------------------

def create_session(session_id: str, workspace_root: str | None, allow_edits: bool) -> dict:
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sessions (id, workspace_root, allow_edits, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, workspace_root, int(allow_edits), now, now),
        )
    return get_session(session_id)


def get_session(session_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def list_sessions(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def update_session(session_id: str, workspace_root: str | None = None,
                   allow_edits: bool | None = None):
    sets, params = [], []
    if workspace_root is not None:
        sets.append("workspace_root = ?")
        params.append(workspace_root)
    if allow_edits is not None:
        sets.append("allow_edits = ?")
        params.append(int(allow_edits))
    sets.append("updated_at = ?")
    params.append(_now())
    params.append(session_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", params)


def add_message(session_id: str, role: str, content: str, *, tool_name: str | None = None,
                tool_call_id: str | None = None, tool_calls: list | None = None,
                hidden: bool = False) -> dict:
    now = _now()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO messages
               (session_id, role, content, tool_name, tool_call_id, tool_calls, hidden, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id, role, content or "", tool_name, tool_call_id,
                json.dumps(tool_calls) if tool_calls else None,
                int(hidden), now,
            ),
        )
        message_id = cur.lastrowid
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
    return {
        "id": message_id, "session_id": session_id, "role": role, "content": content or "",
        "tool_name": tool_name, "tool_call_id": tool_call_id,
        "tool_calls": tool_calls, "hidden": hidden, "created_at": now,
    }


def list_messages(session_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,)
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["tool_calls"] = json.loads(d["tool_calls"]) if d["tool_calls"] else None
        d["hidden"] = bool(d["hidden"])
        result.append(d)
    return result


def delete_session(session_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def workspace_in_use(path: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE workspace_root = ? LIMIT 1", (path,)
        ).fetchone()
        return row is not None


def unregister_workspace(path: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM workspaces WHERE path = ?", (path,))


def purge_expired_sessions(ttl_minutes: int) -> int:
    if ttl_minutes <= 0:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)).isoformat()
    with get_conn() as conn:
        expired = [r["id"] for r in conn.execute(
            "SELECT id FROM sessions WHERE updated_at < ?", (cutoff,)
        ).fetchall()]
        for session_id in expired:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return len(expired)
