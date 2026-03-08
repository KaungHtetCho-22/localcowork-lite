"""
SQLite persistence for conversation sessions.
Stores full message history as JSONL per session.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(".data/sessions.db")


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    """Create tables if they don't exist. Call once at startup."""
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role      TEXT NOT NULL,
                content   TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)


def save_message(session_id: str, role: str, content: dict | str):
    """Append one message to a session."""
    now = datetime.now(timezone.utc).isoformat()
    raw = json.dumps(content) if isinstance(content, dict) else content
    with _conn() as con:
        con.execute("""
            INSERT INTO sessions (session_id, created_at, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at
        """, (session_id, now, now))
        con.execute("""
            INSERT INTO messages (session_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
        """, (session_id, role, raw, now))


def load_messages(session_id: str) -> list[dict]:
    """Load full message history for a session."""
    with _conn() as con:
        rows = con.execute("""
            SELECT role, content FROM messages
            WHERE session_id = ?
            ORDER BY id ASC
        """, (session_id,)).fetchall()
    result = []
    for row in rows:
        try:
            result.append(json.loads(row["content"]))
        except json.JSONDecodeError:
            result.append({"role": row["role"], "content": row["content"]})
    return result


def delete_session(session_id: str):
    """Delete all messages for a session."""
    with _conn() as con:
        con.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        con.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def list_sessions() -> list[dict]:
    """List all sessions with metadata."""
    with _conn() as con:
        rows = con.execute("""
            SELECT s.session_id, s.created_at, s.updated_at,
                   COUNT(m.id) as message_count
            FROM sessions s
            LEFT JOIN messages m ON s.session_id = m.session_id
            GROUP BY s.session_id
            ORDER BY s.updated_at DESC
        """).fetchall()
    return [dict(r) for r in rows]