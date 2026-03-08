"""
tests/test_tool_router.py
Tests for backend/agent_core/tool_router.py — tool registry, schemas, dispatch, risk.

Run:
    pytest tests/test_tool_router.py -v
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_registry():
    """
    Isolate _REGISTRY between tests by saving and restoring it.
    Prevents one test's registered tools from leaking into another.
    """
    from backend.agent_core import tool_router
    original = dict(tool_router._REGISTRY)
    yield
    tool_router._REGISTRY.clear()
    tool_router._REGISTRY.update(original)


@pytest.fixture()
def router():
    from backend.agent_core import tool_router
    return tool_router


# ── register_tool ─────────────────────────────────────────────────────────────

class TestRegisterTool:
    async def _noop(self, **kwargs):
        return {"result": "ok"}

    def test_registers_tool_in_registry(self, router):
        async def handler(x: str): return {"result": x}
        router.register_tool("test", "echo", "Echo input", {"type": "object", "properties": {}}, handler)
        assert "test.echo" in router._REGISTRY

    def test_default_risk_is_safe(self, router):
        async def handler(): return {}
        router.register_tool("test", "read", "Read something", {"type": "object", "properties": {}}, handler)
        assert router._REGISTRY["test.read"]["risk"] == "safe"

    def test_custom_risk_stored(self, router):
        async def handler(): return {}
        router.register_tool("test", "send", "Send email", {"type": "object", "properties": {}}, handler, risk="destructive")
        assert router._REGISTRY["test.send"]["risk"] == "destructive"

    def test_overwrites_existing_tool(self, router):
        async def v1(): return {"v": 1}
        async def v2(): return {"v": 2}
        router.register_tool("test", "tool", "v1", {"type": "object", "properties": {}}, v1)
        router.register_tool("test", "tool", "v2", {"type": "object", "properties": {}}, v2)
        assert router._REGISTRY["test.tool"]["description"] == "v2"


# ── get_tool_schemas ──────────────────────────────────────────────────────────

class TestGetToolSchemas:
    def test_returns_list(self, router):
        schemas = router.get_tool_schemas()
        assert isinstance(schemas, list)

    def test_schema_has_required_fields(self, router):
        async def handler(query: str): return {}
        router.register_tool(
            "test", "search", "Search kb",
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            handler,
        )
        schemas = {s["function"]["name"]: s for s in router.get_tool_schemas()}
        schema = schemas["test.search"]
        assert schema["type"] == "function"
        assert "name" in schema["function"]
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]

    def test_tool_name_format_is_server_dot_name(self, router):
        async def handler(): return {}
        router.register_tool("myserver", "mytool", "desc", {"type": "object", "properties": {}}, handler)
        names = [s["function"]["name"] for s in router.get_tool_schemas()]
        assert "myserver.mytool" in names


# ── get_risk ──────────────────────────────────────────────────────────────────

class TestGetRisk:
    def test_returns_safe_for_unknown_tool(self, router):
        assert router.get_risk("nonexistent.tool") == "safe"

    def test_returns_correct_risk_for_registered_tool(self, router):
        async def handler(): return {}
        router.register_tool("g", "send_email", "Send", {"type": "object", "properties": {}}, handler, risk="destructive")
        assert router.get_risk("g.send_email") == "destructive"

    @pytest.mark.parametrize("risk", ["safe", "write", "destructive"])
    def test_all_risk_levels_stored(self, router, risk):
        async def handler(): return {}
        router.register_tool("t", f"tool_{risk}", "desc", {"type": "object", "properties": {}}, handler, risk=risk)
        assert router.get_risk(f"t.tool_{risk}") == risk


# ── dispatch ──────────────────────────────────────────────────────────────────

class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_calls_handler(self, router):
        called_with = {}

        async def handler(query: str):
            called_with["query"] = query
            return {"hits": 3}

        router.register_tool("kb", "search", "Search", {"type": "object", "properties": {}}, handler)
        result = await router.dispatch("kb.search", {"query": "transformers"}, session_id="s1")
        assert result["success"] is True
        assert called_with["query"] == "transformers"

    @pytest.mark.asyncio
    async def test_dispatch_returns_result(self, router):
        async def handler():
            return {"files": ["a.pdf", "b.pdf"]}

        router.register_tool("fs", "list_dir", "List", {"type": "object", "properties": {}}, handler)
        result = await router.dispatch("fs.list_dir", {}, session_id="s1")
        assert result["result"]["files"] == ["a.pdf", "b.pdf"]

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool_returns_error(self, router):
        result = await router.dispatch("unknown.tool", {}, session_id="s1")
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_dispatch_handler_exception_caught(self, router):
        async def bad_handler():
            raise ValueError("something went wrong")

        router.register_tool("bad", "tool", "Bad", {"type": "object", "properties": {}}, bad_handler)
        result = await router.dispatch("bad.tool", {}, session_id="s1")
        assert result["success"] is False
        assert "something went wrong" in result["error"]

    @pytest.mark.asyncio
    async def test_dispatch_includes_latency_ms(self, router):
        async def handler():
            return {"ok": True}

        router.register_tool("t", "fast", "Fast", {"type": "object", "properties": {}}, handler)
        result = await router.dispatch("t.fast", {}, session_id="s1")
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], (int, float))
        assert result["latency_ms"] >= 0