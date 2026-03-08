"""
ToolRouter — discovers tools from all MCP servers and routes
tool_call requests from the LLM to the correct server.
"""
from __future__ import annotations

import time
import importlib
from typing import Any, Callable, Awaitable

from backend.agent_core.audit import audit


# Each MCP server registers itself here at import time
_REGISTRY: dict[str, dict] = {}  # tool_name → {server, schema, handler}


def register_tool(
    server: str,
    name: str,
    description: str,
    parameters: dict,
    handler: Callable[..., Awaitable[Any]],
) -> None:
    """Called by each MCP server module to register its tools."""
    full_name = f"{server}.{name}"
    _REGISTRY[full_name] = {
        "server": server,
        "name": name,
        "full_name": full_name,
        "description": description,
        "parameters": parameters,
        "handler": handler,
    }


def get_tool_schemas() -> list[dict]:
    """Return OpenAI-compatible tool definitions for all registered tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": entry["full_name"],
                "description": entry["description"],
                "parameters": entry["parameters"],
            },
        }
        for entry in _REGISTRY.values()
    ]


def list_tools() -> list[dict]:
    return [
        {
            "full_name": e["full_name"],
            "server": e["server"],
            "description": e["description"],
        }
        for e in _REGISTRY.values()
    ]


async def dispatch(
    tool_name: str,
    arguments: dict,
    session_id: str,
) -> dict:
    """
    Execute a tool by name, log the result to the audit trail,
    and return a standardized response dict.
    """
    entry = _REGISTRY.get(tool_name)
    if not entry:
        return {"success": False, "error": f"Unknown tool: {tool_name}", "result": None}

    handler = entry["handler"]
    server = entry["server"]
    t0 = time.perf_counter()

    try:
        result = await handler(**arguments)
        latency_ms = (time.perf_counter() - t0) * 1000
        await audit.log(
            session_id=session_id,
            tool_name=tool_name,
            server=server,
            arguments=arguments,
            result=result,
            success=True,
            latency_ms=latency_ms,
        )
        return {"success": True, "result": result, "latency_ms": round(latency_ms, 1)}
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        await audit.log(
            session_id=session_id,
            tool_name=tool_name,
            server=server,
            arguments=arguments,
            result=None,
            success=False,
            latency_ms=latency_ms,
            error=str(exc),
        )
        return {"success": False, "error": str(exc), "result": None, "latency_ms": round(latency_ms, 1)}


def _autodiscover():
    """Import all MCP server modules so they self-register."""
    servers = ["knowledge", "filesystem", "document", "audit", "system", "google"]
    for s in servers:
        try:
            importlib.import_module(f"backend.mcp_servers.{s}.server")
        except ImportError as e:
            print(f"[ToolRouter] Warning: could not load server '{s}': {e}")


_autodiscover()
