"""
Plain sqlite3 (no SQLAlchemy) — this is the "do we need memory storage"
answer for the MVP: yes, but only enough to remember past runs so the
report-renderer's on-disk files are discoverable and so a future UI has
something to list. See README's "Memory / storage roadmap" for when to
graduate this to Postgres + object storage + a vector store.
"""
import json
import sqlite3
from contextlib import contextmanager
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
"""


def _db_path() -> Path:
    return Path(settings.database_path)


@contextmanager
def get_conn():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(SCHEMA)


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
