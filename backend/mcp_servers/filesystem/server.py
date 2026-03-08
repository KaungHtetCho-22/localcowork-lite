"""
Filesystem MCP Server — sandboxed file operations
Tools: list_dir, read_file, search_files
"""
from __future__ import annotations

from pathlib import Path

from backend.agent_core.tool_router import register_tool
from backend.config import settings


def _safe_path(p: str) -> Path:
    """Resolve path and enforce sandbox boundary."""
    resolved = Path(p).expanduser().resolve()
    sandbox = settings.sandbox_path
    try:
        resolved.relative_to(sandbox)
    except ValueError:
        raise PermissionError(
            f"Access denied: '{resolved}' is outside sandbox '{sandbox}'"
        )
    return resolved


async def list_dir(path: str) -> dict:
    """List files and directories at the given path."""
    target = _safe_path(path)
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"Not a directory: {target}")

    items = []
    for item in sorted(target.iterdir()):
        stat = item.stat()
        items.append({
            "name": item.name,
            "type": "dir" if item.is_dir() else "file",
            "size_bytes": stat.st_size if item.is_file() else None,
            "suffix": item.suffix.lower() if item.is_file() else None,
        })

    return {"path": str(target), "items": items, "count": len(items)}


async def read_file(path: str, max_chars: int = 4000) -> dict:
    """Read the contents of a text file (truncated to max_chars)."""
    target = _safe_path(path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {target}")
    if not target.is_file():
        raise IsADirectoryError(f"Path is a directory: {target}")

    content = target.read_text(encoding="utf-8", errors="replace")
    truncated = len(content) > max_chars

    return {
        "path": str(target),
        "content": content[:max_chars],
        "truncated": truncated,
        "total_chars": len(content),
    }


async def search_files(directory: str, pattern: str) -> dict:
    """Search for files matching a glob pattern under a directory."""
    target = _safe_path(directory)
    if not target.is_dir():
        raise NotADirectoryError(f"Not a directory: {target}")

    matches = [
        {
            "path": str(p),
            "name": p.name,
            "size_bytes": p.stat().st_size,
        }
        for p in sorted(target.rglob(pattern))
        if p.is_file()
    ]

    return {"directory": str(target), "pattern": pattern, "matches": matches, "count": len(matches)}


# ── Register ──────────────────────────────────────────────────────────────────

register_tool(
    server="filesystem",
    name="list_dir",
    description="List files and subdirectories at a given path (sandboxed).",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to list"},
        },
        "required": ["path"],
    },
    handler=list_dir,
)

register_tool(
    server="filesystem",
    name="read_file",
    description="Read the text content of a file (sandboxed, truncated to 4000 chars by default).",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read"},
            "max_chars": {"type": "integer", "description": "Max characters to return", "default": 4000},
        },
        "required": ["path"],
    },
    handler=read_file,
)

register_tool(
    server="filesystem",
    name="search_files",
    description="Search for files matching a glob pattern under a directory (e.g. '*.pdf', '**/*.md').",
    parameters={
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "Root directory to search under"},
            "pattern": {"type": "string", "description": "Glob pattern e.g. '*.pdf', '**/*.txt'"},
        },
        "required": ["directory", "pattern"],
    },
    handler=search_files,
)
