"""
tests/test_db.py
Tests for backend/agent_core/db.py — SQLite session persistence layer.

Run:
    pytest tests/test_db.py -v
"""
import pytest
from unittest.mock import patch


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """
    Redirect DB_PATH to a fresh temp file for every test so tests never
    share state and can run in any order.
    """
    import backend.agent_core.db as db_module
    db_file = tmp_path / "test_sessions.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_file)
    db_module.init_db()
    yield


@pytest.fixture()
def db():
    from backend.agent_core import db as _db
    return _db


# ── init_db ───────────────────────────────────────────────────────────────────

class TestInitDb:
    def test_creates_sessions_table(self, tmp_path, db):
        import sqlite3
        import backend.agent_core.db as db_module
        con = sqlite3.connect(str(db_module.DB_PATH))
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "sessions" in tables

    def test_creates_messages_table(self, tmp_path, db):
        import sqlite3
        import backend.agent_core.db as db_module
        con = sqlite3.connect(str(db_module.DB_PATH))
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "messages" in tables

    def test_idempotent(self, db):
        """Calling init_db multiple times must not raise."""
        db.init_db()
        db.init_db()


# ── save_message / load_messages ──────────────────────────────────────────────

class TestSaveAndLoad:
    def test_single_user_message(self, db):
        db.save_message("s1", "user", {"role": "user", "content": "hello"})
        msgs = db.load_messages("s1")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "hello"
        assert msgs[0]["role"] == "user"

    def test_multiple_roles_preserved(self, db):
        sid = "multi"
        db.save_message(sid, "user",      {"role": "user",      "content": "q"})
        db.save_message(sid, "assistant", {"role": "assistant",  "content": "a"})
        db.save_message(sid, "tool",      {"role": "tool",       "content": "{}"})
        msgs = db.load_messages(sid)
        assert [m["role"] for m in msgs] == ["user", "assistant", "tool"]

    def test_insertion_order_preserved(self, db):
        sid = "order"
        for i in range(5):
            db.save_message(sid, "user", {"role": "user", "content": str(i)})
        msgs = db.load_messages(sid)
        assert [m["content"] for m in msgs] == ["0", "1", "2", "3", "4"]

    def test_empty_for_unknown_session(self, db):
        assert db.load_messages("does-not-exist") == []

    def test_sessions_are_isolated(self, db):
        db.save_message("s-a", "user", {"role": "user", "content": "a"})
        db.save_message("s-b", "user", {"role": "user", "content": "b"})
        assert len(db.load_messages("s-a")) == 1
        assert len(db.load_messages("s-b")) == 1

    def test_accepts_string_content(self, db):
        """save_message should handle raw strings, not just dicts."""
        db.save_message("s-str", "user", "plain string")
        msgs = db.load_messages("s-str")
        assert len(msgs) == 1

    def test_tool_call_dict_roundtrip(self, db):
        """Complex nested dicts must survive JSON roundtrip."""
        payload = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "tc1", "function": {"name": "knowledge.search", "arguments": '{"query":"test"}'}}
            ],
        }
        db.save_message("s-tc", "assistant", payload)
        msgs = db.load_messages("s-tc")
        assert msgs[0]["tool_calls"][0]["id"] == "tc1"

    def test_upserts_session_row_on_repeat_save(self, db):
        """Multiple saves to same session should not duplicate session rows."""
        sid = "upsert"
        db.save_message(sid, "user", {"role": "user", "content": "1"})
        db.save_message(sid, "user", {"role": "user", "content": "2"})
        sessions = {s["session_id"]: s for s in db.list_sessions()}
        assert sessions[sid]["message_count"] == 2


# ── delete_session ────────────────────────────────────────────────────────────

class TestDeleteSession:
    def test_removes_all_messages(self, db):
        sid = "del-1"
        db.save_message(sid, "user", {"role": "user", "content": "bye"})
        db.delete_session(sid)
        assert db.load_messages(sid) == []

    def test_removes_session_row(self, db):
        sid = "del-2"
        db.save_message(sid, "user", {"role": "user", "content": "bye"})
        db.delete_session(sid)
        ids = {s["session_id"] for s in db.list_sessions()}
        assert sid not in ids

    def test_does_not_affect_other_sessions(self, db):
        db.save_message("keep",   "user", {"role": "user", "content": "keep"})
        db.save_message("delete", "user", {"role": "user", "content": "delete"})
        db.delete_session("delete")
        assert len(db.load_messages("keep")) == 1

    def test_nonexistent_session_does_not_raise(self, db):
        db.delete_session("ghost-session")


# ── list_sessions ─────────────────────────────────────────────────────────────

class TestListSessions:
    def test_empty_initially(self, db):
        assert db.list_sessions() == []

    def test_returns_all_session_ids(self, db):
        db.save_message("s-a", "user", {"role": "user", "content": "a"})
        db.save_message("s-b", "user", {"role": "user", "content": "b"})
        ids = {s["session_id"] for s in db.list_sessions()}
        assert ids == {"s-a", "s-b"}

    def test_message_count_is_accurate(self, db):
        sid = "count"
        for _ in range(4):
            db.save_message(sid, "user", {"role": "user", "content": "x"})
        sessions = {s["session_id"]: s for s in db.list_sessions()}
        assert sessions[sid]["message_count"] == 4

    def test_ordered_by_updated_at_descending(self, db):
        """Most recently updated session should appear first."""
        import time
        db.save_message("old", "user", {"role": "user", "content": "old"})
        time.sleep(0.01)
        db.save_message("new", "user", {"role": "user", "content": "new"})
        sessions = db.list_sessions()
        assert sessions[0]["session_id"] == "new"

    # def test_has_created_at_and_updated_at(self, db):
    #     db.save_message("ts", "user", {"role": "user", "content": "x"})
    #     session = db.list_sessions()[0]
    #     assert "created_at" in session
    #     assert "updated_at" in sessions

    def test_has_created_at_and_updated_at(self, db):
        db.save_message("ts", "user", {"role": "user", "content": "x"})
        all_sessions = db.list_sessions()
        assert len(all_sessions) > 0
        session = all_sessions[0]
        assert "created_at" in session
        assert "updated_at" in session