"""
Audit logger — every tool call is appended to a JSONL file.
Mirrors LocalCowork's audit trail design.
"""
from __future__ import annotations

import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import settings


class AuditLogger:
    def __init__(self):
        self._path = settings.audit_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def log(
        self,
        session_id: str,
        tool_name: str,
        server: str,
        arguments: dict,
        result: Any,
        success: bool,
        latency_ms: float,
        error: str | None = None,
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "server": server,
            "tool": tool_name,
            "arguments": arguments,
            "success": success,
            "latency_ms": round(latency_ms, 1),
            "result_preview": _preview(result),
            "error": error,
        }
        async with self._lock:
            with open(self._path, "a") as f:
                f.write(json.dumps(entry) + "\n")

    async def get_log(
        self,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        if not self._path.exists():
            return []
        entries = []
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if session_id is None or entry.get("session_id") == session_id:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
        return entries[-limit:]

    async def summary(self, session_id: str | None = None) -> dict:
        entries = await self.get_log(session_id=session_id, limit=10_000)
        total = len(entries)
        succeeded = sum(1 for e in entries if e["success"])
        servers_used = list({e["server"] for e in entries})
        tools_used = list({e["tool"] for e in entries})
        avg_latency = (
            sum(e["latency_ms"] for e in entries) / total if total > 0 else 0
        )
        return {
            "total_calls": total,
            "succeeded": succeeded,
            "failed": total - succeeded,
            "success_rate": round(succeeded / total * 100, 1) if total > 0 else 0,
            "avg_latency_ms": round(avg_latency, 1),
            "servers_used": servers_used,
            "tools_used": tools_used,
        }


def _preview(result: Any, max_len: int = 200) -> str:
    try:
        s = json.dumps(result) if not isinstance(result, str) else result
        return s[:max_len] + ("..." if len(s) > max_len else "")
    except Exception:
        return str(result)[:max_len]


audit = AuditLogger()
