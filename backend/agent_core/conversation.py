"""
ConversationManager — the agent loop.

Each turn:
1. Append user message to history
2. Call LLM with tools
3. If LLM emits tool_calls → optionally confirm (HITL) → dispatch → append results → call LLM again
4. Repeat up to MAX_TOOL_CALLS times
5. Stream final assistant response

Mirrors LocalCowork's ConversationManager + Orchestrator design.
"""
from __future__ import annotations

import json
import asyncio
from typing import AsyncIterator

from backend.inference.client import inference
from backend.agent_core.tool_router import get_tool_schemas, dispatch, get_risk
from backend.agent_core.db import save_message, load_messages, delete_session
from backend.config import settings

SYSTEM_PROMPT = """You are LocalCowork, a private on-device AI assistant.
You have access to tools for managing files, documents, knowledge base, system info, and Google Workspace.
All processing happens locally — no data ever leaves this machine.

Rules:
- Always prefer using tools over guessing when a tool can answer better
- Be concise in your final answer
- After tool results, synthesize a clear, human-readable response
- Never hallucinate tool names — only call tools from the provided list
- When a URL or link is available in tool results, always render it as a markdown hyperlink e.g. [View Event](https://...)
- When creating calendar events with reminders, confirm the reminder time clearly to the user
"""


class ConversationManager:
    def __init__(self, session_id: str):
        self.session_id = session_id
        stored = load_messages(session_id)
        if stored:
            self._history = stored
        else:
            self._history = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._confirm_event = asyncio.Event()
        self._confirm_approved: bool = False

    def resolve_confirmation(self, approved: bool):
        """Called from main.py when user approves or rejects a tool call."""
        self._confirm_approved = approved
        self._confirm_event.set()

    def reset(self):
        delete_session(self.session_id)
        self._history = [{"role": "system", "content": SYSTEM_PROMPT}]

    async def turn(self, user_message: str, hitl: bool = True) -> AsyncIterator[dict]:
        """
        Process one user turn. Yields streaming events:
          {"type": "tool_confirm",  "tool": ..., "arguments": ..., "tool_call_id": ..., "risk": ...}
          {"type": "tool_call",     "tool": ..., "arguments": ...}
          {"type": "tool_result",   "tool": ..., "success": ..., "result": ..., "error": ..., "latency_ms": ...}
          {"type": "text_delta",    "content": ...}
          {"type": "done"}
        """
        self._history.append({"role": "user", "content": user_message})
        save_message(self.session_id, "user", {"role": "user", "content": user_message})

        tools = get_tool_schemas()

        for _ in range(settings.max_tool_calls):
            response = await inference.chat(self._history, tools=tools)

            # No tool calls → stream final text response and exit
            if not response.get("tool_calls"):
                assistant_msg = {"role": "assistant", "content": response["content"]}
                self._history.append(assistant_msg)
                save_message(self.session_id, "assistant", assistant_msg)
                yield {"type": "text_delta", "content": response["content"]}
                yield {"type": "done"}
                return

            # Append assistant message with tool_calls to history
            assistant_msg = {
                "role": "assistant",
                "content": response["content"],
                "tool_calls": response["tool_calls"],
            }
            self._history.append(assistant_msg)
            save_message(self.session_id, "assistant", assistant_msg)

            # Dispatch each tool call (single loop — no duplicates)
            for tc in response["tool_calls"]:
                tool_name = tc["function"]["name"]
                try:
                    arguments = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {}

                risk = get_risk(tool_name)

                # ── Human-in-the-loop: pause on write/destructive tools ────────
                if hitl and risk in ("write", "destructive"):
                    self._confirm_event.clear()
                    self._confirm_approved = False

                    yield {
                        "type": "tool_confirm",
                        "tool": tool_name,
                        "arguments": arguments,
                        "tool_call_id": tc["id"],
                        "risk": risk,
                    }

                    # Block here until resolve_confirmation() is called by main.py
                    await self._confirm_event.wait()

                    if not self._confirm_approved:
                        # User rejected — record it and skip execution
                        tool_msg = {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": "User rejected this tool call.",
                        }
                        self._history.append(tool_msg)
                        save_message(self.session_id, "tool", tool_msg)

                        yield {
                            "type": "tool_result",
                            "tool": tool_name,
                            "success": False,
                            "result": None,
                            "error": "Rejected by user",
                            "latency_ms": 0,
                        }
                        continue
                # ─────────────────────────────────────────────────────────────

                yield {"type": "tool_call", "tool": tool_name, "arguments": arguments}

                result = await dispatch(
                    tool_name=tool_name,
                    arguments=arguments,
                    session_id=self.session_id,
                )

                yield {
                    "type": "tool_result",
                    "tool": tool_name,
                    "success": result["success"],
                    "result": result.get("result"),
                    "error": result.get("error"),
                    "latency_ms": result.get("latency_ms", 0),
                }

                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result.get("result") or result.get("error")),
                }
                self._history.append(tool_msg)
                save_message(self.session_id, "tool", tool_msg)

        # Exceeded max tool calls — synthesize final response with what we have
        final = await inference.chat(self._history, tools=None)
        final_msg = {"role": "assistant", "content": final["content"]}
        self._history.append(final_msg)
        save_message(self.session_id, "assistant", final_msg)
        yield {"type": "text_delta", "content": final["content"]}
        yield {"type": "done"}

    @property
    def history(self) -> list[dict]:
        return [m for m in self._history if m["role"] != "system"]