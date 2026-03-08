"""
tests/test_conversation.py
Tests for backend/agent_core/conversation.py — agent loop and HITL.

Run:
    pytest tests/test_conversation.py -v
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_text_response(content: str) -> dict:
    """Simulate an LLM response with no tool calls."""
    return {"content": content, "tool_calls": None}


def make_tool_response(tool_name: str, arguments: dict, call_id: str = "tc1") -> dict:
    """Simulate an LLM response that calls a tool."""
    return {
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments),
                },
            }
        ],
    }


async def collect_events(cm, user_message: str, hitl: bool = True) -> list[dict]:
    """Drain the turn() async generator into a list."""
    events = []
    async for event in cm.turn(user_message, hitl=hitl):
        events.append(event)
    return events


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_inference():
    with patch("backend.agent_core.conversation.inference") as m:
        yield m


@pytest.fixture()
def mock_dispatch():
    with patch("backend.agent_core.conversation.dispatch") as m:
        m.return_value = AsyncMock(return_value={
            "success": True,
            "result": {"found": True},
            "latency_ms": 10,
        })
        yield m


@pytest.fixture()
def mock_db():
    with patch("backend.agent_core.conversation.save_message") as sm, \
         patch("backend.agent_core.conversation.load_messages", return_value=[]) as lm, \
         patch("backend.agent_core.conversation.delete_session") as ds:
        yield {"save": sm, "load": lm, "delete": ds}


@pytest.fixture()
def cm(mock_db):
    from backend.agent_core.conversation import ConversationManager
    return ConversationManager("test-session")


# ── Initialization ────────────────────────────────────────────────────────────

class TestInit:
    def test_starts_with_system_prompt(self, cm):
        assert cm._history[0]["role"] == "system"
        assert "LocalCowork" in cm._history[0]["content"]

    def test_loads_existing_history_from_db(self, mock_db):
        stored = [
            {"role": "system",    "content": "You are LocalCowork..."},
            {"role": "user",      "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        mock_db["load"].return_value = stored
        from backend.agent_core.conversation import ConversationManager
        cm = ConversationManager("existing-session")
        assert cm._history == stored

    def test_history_property_excludes_system(self, cm):
        roles = [m["role"] for m in cm.history]
        assert "system" not in roles

    def test_reset_clears_history(self, cm, mock_db):
        cm._history.append({"role": "user", "content": "test"})
        cm.reset()
        assert len(cm._history) == 1
        assert cm._history[0]["role"] == "system"
        mock_db["delete"].assert_called_once_with("test-session")


# ── Simple text turn ──────────────────────────────────────────────────────────

class TestSimpleTurn:
    @pytest.mark.asyncio
    async def test_yields_text_delta_and_done(self, cm, mock_inference, mock_db):
        mock_inference.chat = AsyncMock(return_value=make_text_response("Hello world"))
        events = await collect_events(cm, "hi")
        types = [e["type"] for e in events]
        assert "text_delta" in types
        assert "done" in types

    @pytest.mark.asyncio
    async def test_text_content_correct(self, cm, mock_inference, mock_db):
        mock_inference.chat = AsyncMock(return_value=make_text_response("Paris"))
        events = await collect_events(cm, "capital of France?")
        text_events = [e for e in events if e["type"] == "text_delta"]
        assert text_events[0]["content"] == "Paris"

    @pytest.mark.asyncio
    async def test_done_is_last_event(self, cm, mock_inference, mock_db):
        mock_inference.chat = AsyncMock(return_value=make_text_response("ok"))
        events = await collect_events(cm, "hello")
        assert events[-1]["type"] == "done"

    @pytest.mark.asyncio
    async def test_user_message_saved_to_db(self, cm, mock_inference, mock_db):
        mock_inference.chat = AsyncMock(return_value=make_text_response("ok"))
        await collect_events(cm, "save me")
        mock_db["save"].assert_any_call(
            "test-session", "user", {"role": "user", "content": "save me"}
        )


# ── Tool call turn ────────────────────────────────────────────────────────────

class TestToolCallTurn:
    @pytest.mark.asyncio
    async def test_yields_tool_call_event(self, cm, mock_inference, mock_dispatch, mock_db):
        mock_inference.chat = AsyncMock(side_effect=[
            make_tool_response("knowledge.search", {"query": "RAG"}),
            make_text_response("Here are results"),
        ])
        mock_dispatch.return_value = {"success": True, "result": {"hits": []}, "latency_ms": 5}
        events = await collect_events(cm, "search for RAG", hitl=False)
        tool_calls = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["tool"] == "knowledge.search"

    @pytest.mark.asyncio
    async def test_yields_tool_result_event(self, cm, mock_inference, mock_dispatch, mock_db):
        mock_inference.chat = AsyncMock(side_effect=[
            make_tool_response("filesystem.list_dir", {"path": "~/Documents"}),
            make_text_response("Found 3 files"),
        ])
        mock_dispatch.return_value = {"success": True, "result": {"files": ["a", "b", "c"]}, "latency_ms": 8}
        events = await collect_events(cm, "list my files", hitl=False)
        results = [e for e in events if e["type"] == "tool_result"]
        assert len(results) == 1
        assert results[0]["success"] is True

    @pytest.mark.asyncio
    async def test_tool_result_appended_to_history(self, cm, mock_inference, mock_dispatch, mock_db):
        mock_inference.chat = AsyncMock(side_effect=[
            make_tool_response("audit.get_summary", {}),
            make_text_response("Summary ready"),
        ])
        mock_dispatch.return_value = {"success": True, "result": {"calls": 5}, "latency_ms": 3}
        await collect_events(cm, "show audit", hitl=False)
        roles = [m["role"] for m in cm._history]
        assert "tool" in roles

    @pytest.mark.asyncio
    async def test_invalid_json_arguments_handled(self, cm, mock_inference, mock_dispatch, mock_db):
        bad_response = {
            "content": None,
            "tool_calls": [{"id": "tc1", "function": {"name": "fs.list_dir", "arguments": "INVALID JSON{"}}],
        }
        mock_inference.chat = AsyncMock(side_effect=[
            bad_response,
            make_text_response("ok"),
        ])
        mock_dispatch.return_value = {"success": True, "result": {}, "latency_ms": 1}
        # Should not raise — bad JSON arguments default to {}
        events = await collect_events(cm, "list files", hitl=False)
        assert any(e["type"] == "done" for e in events)


# ── HITL ──────────────────────────────────────────────────────────────────────

class TestHITL:
    @pytest.mark.asyncio
    async def test_write_tool_emits_tool_confirm(self, mock_db):
        """A write-risk tool should pause and emit tool_confirm before executing."""
        from backend.agent_core.conversation import ConversationManager

        with patch("backend.agent_core.conversation.inference") as mock_inf, \
             patch("backend.agent_core.conversation.dispatch") as mock_disp, \
             patch("backend.agent_core.conversation.get_risk", return_value="write"):

            mock_inf.chat = AsyncMock(side_effect=[
                make_tool_response("knowledge.ingest_document", {"path": "paper.pdf"}),
                make_text_response("Ingested"),
            ])
            mock_disp.return_value = {"success": True, "result": {}, "latency_ms": 5}

            cm = ConversationManager("hitl-session")

            events = []
            confirmed = False

            async def run():
                nonlocal confirmed
                async for event in cm.turn("ingest paper.pdf", hitl=True):
                    events.append(event)
                    if event["type"] == "tool_confirm" and not confirmed:
                        confirmed = True
                        cm.resolve_confirmation(True)

            await run()

        confirm_events = [e for e in events if e["type"] == "tool_confirm"]
        assert len(confirm_events) == 1
        assert confirm_events[0]["risk"] == "write"

    @pytest.mark.asyncio
    async def test_rejected_tool_skips_dispatch(self, mock_db):
        """Rejecting a tool_confirm should skip dispatch and record error."""
        from backend.agent_core.conversation import ConversationManager

        with patch("backend.agent_core.conversation.inference") as mock_inf, \
             patch("backend.agent_core.conversation.dispatch") as mock_disp, \
             patch("backend.agent_core.conversation.get_risk", return_value="destructive"):

            mock_inf.chat = AsyncMock(side_effect=[
                make_tool_response("google.send_email", {"to": "x@x.com", "subject": "Hi"}),
                make_text_response("Cancelled"),
            ])
            mock_disp.return_value = {"success": True, "result": {}, "latency_ms": 5}

            cm = ConversationManager("reject-session")
            events = []

            async def run():
                async for event in cm.turn("send email", hitl=True):
                    events.append(event)
                    if event["type"] == "tool_confirm":
                        cm.resolve_confirmation(False)

            await run()

        mock_disp.assert_not_called()
        rejected = [e for e in events if e["type"] == "tool_result" and e.get("error") == "Rejected by user"]
        assert len(rejected) == 1

    @pytest.mark.asyncio
    async def test_safe_tool_bypasses_hitl(self, mock_db):
        """Safe tools should execute immediately without emitting tool_confirm."""
        from backend.agent_core.conversation import ConversationManager

        with patch("backend.agent_core.conversation.inference") as mock_inf, \
             patch("backend.agent_core.conversation.dispatch") as mock_disp, \
             patch("backend.agent_core.conversation.get_risk", return_value="safe"):

            mock_inf.chat = AsyncMock(side_effect=[
                make_tool_response("knowledge.search", {"query": "attention"}),
                make_text_response("Results here"),
            ])
            mock_disp.return_value = {"success": True, "result": {"hits": []}, "latency_ms": 2}

            cm = ConversationManager("safe-session")
            events = await collect_events(cm, "search for attention", hitl=True)

        confirm_events = [e for e in events if e["type"] == "tool_confirm"]
        assert len(confirm_events) == 0

    @pytest.mark.asyncio
    async def test_hitl_false_skips_all_confirmation(self, mock_db):
        """hitl=False should bypass confirmation even for destructive tools."""
        from backend.agent_core.conversation import ConversationManager

        with patch("backend.agent_core.conversation.inference") as mock_inf, \
             patch("backend.agent_core.conversation.dispatch") as mock_disp, \
             patch("backend.agent_core.conversation.get_risk", return_value="destructive"):

            mock_inf.chat = AsyncMock(side_effect=[
                make_tool_response("google.send_email", {"to": "x@x.com"}),
                make_text_response("Sent"),
            ])
            mock_disp.return_value = {"success": True, "result": {}, "latency_ms": 1}

            cm = ConversationManager("no-hitl-session")
            events = await collect_events(cm, "send email", hitl=False)

        mock_disp.assert_called_once()
        confirm_events = [e for e in events if e["type"] == "tool_confirm"]
        assert len(confirm_events) == 0