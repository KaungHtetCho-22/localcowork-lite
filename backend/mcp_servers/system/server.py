"""
System MCP Server — OS information, processes, disk usage
Tools: get_system_info, get_disk_usage, get_running_processes
"""
from __future__ import annotations

import platform
import psutil
from datetime import datetime

from backend.agent_core.tool_router import register_tool


async def get_system_info() -> dict:
    """Get OS, CPU, RAM, and uptime information."""
    uname = platform.uname()
    mem = psutil.virtual_memory()
    cpu_freq = psutil.cpu_freq()

    return {
        "os": f"{uname.system} {uname.release}",
        "hostname": uname.node,
        "architecture": uname.machine,
        "cpu": {
            "model": uname.processor or platform.processor(),
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "usage_percent": psutil.cpu_percent(interval=0.5),
            "frequency_mhz": round(cpu_freq.current, 1) if cpu_freq else None,
        },
        "memory": {
            "total_gb": round(mem.total / 1e9, 2),
            "used_gb": round(mem.used / 1e9, 2),
            "available_gb": round(mem.available / 1e9, 2),
            "percent_used": mem.percent,
        },
        "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
    }


async def get_disk_usage(path: str = "/") -> dict:
    """Get disk usage for a given mount point."""
    usage = psutil.disk_usage(path)
    return {
        "path": path,
        "total_gb": round(usage.total / 1e9, 2),
        "used_gb": round(usage.used / 1e9, 2),
        "free_gb": round(usage.free / 1e9, 2),
        "percent_used": usage.percent,
    }


async def get_running_processes(limit: int = 10) -> dict:
    """Get top processes sorted by CPU usage."""
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
        try:
            procs.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    procs = sorted(procs, key=lambda x: x["cpu_percent"] or 0, reverse=True)[:limit]
    return {"processes": procs, "total_shown": len(procs)}


# ── Register ──────────────────────────────────────────────────────────────────

register_tool(
    server="system",
    name="get_system_info",
    description="Get system information: OS, CPU model, core count, RAM usage, and uptime.",
    parameters={"type": "object", "properties": {}},
    handler=get_system_info,
)

register_tool(
    server="system",
    name="get_disk_usage",
    description="Get disk usage (total, used, free) for a mount point. Defaults to '/'.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Mount point path, e.g. '/' or '/home'", "default": "/"},
        },
    },
    handler=get_disk_usage,
)

register_tool(
    server="system",
    name="get_running_processes",
    description="List top running processes sorted by CPU usage.",
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Number of processes to return (default 10)", "default": 10},
        },
    },
    handler=get_running_processes,
)