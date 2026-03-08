"""
Audit MCP Server — read the tool call audit trail
Tools: get_tool_log, get_summary
"""
from __future__ import annotations

from backend.agent_core.tool_router import register_tool
from backend.agent_core.audit import audit as _audit


async def get_tool_log(session_id: str | None = None, limit: int = 20) -> dict:
    """Retrieve recent tool call log entries."""
    entries = await _audit.get_log(session_id=session_id, limit=limit)
    return {"entries": entries, "count": len(entries)}


async def get_summary(session_id: str | None = None) -> dict:
    """Get a summary of all tool calls: counts, success rate, avg latency."""
    return await _audit.summary(session_id=session_id)


# ── Register ──────────────────────────────────────────────────────────────────

register_tool(
    server="audit",
    name="get_tool_log",
    description="Retrieve recent tool call history showing what the agent did, when, and whether it succeeded.",
    parameters={
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Filter by session ID (optional)"},
            "limit": {"type": "integer", "description": "Max entries to return (default 20)", "default": 20},
        },
    },
    handler=get_tool_log,
)

register_tool(
    server="audit",
    name="get_summary",
    description="Get an audit summary: total calls, success rate, average latency, tools used.",
    parameters={
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Filter by session ID (optional)"},
        },
    },
    handler=get_summary,
)
