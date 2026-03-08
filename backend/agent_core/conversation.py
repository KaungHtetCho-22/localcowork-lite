"""
ConversationManager — the agent loop.

Each turn:
1. Append user message to history
2. Call LLM with tools
3. If LLM emits tool_calls → dispatch each → append results → call LLM again
4. Repeat up to MAX_TOOL_CALLS times
5. Stream final assistant response

Mirrors LocalCowork's ConversationManager + Orchestrator design.
"""
from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

from backend.inference.client import inference
from backend.agent_core.tool_router import get_tool_schemas, dispatch
from backend.config import settings
from backend.agent_core.db import save_message, load_messages, delete_session

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
        # Load existing history from DB, or start fresh
        stored = load_messages(session_id)
        if stored:
            self._history = stored
        else:
            self._history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def reset(self):
        delete_session(self.session_id)
        self._history = [{"role": "system", "content": SYSTEM_PROMPT}]

    async def turn(self, user_message: str) -> AsyncIterator[dict]:
        """
        Process one user turn. Yields streaming events:
          {"type": "tool_call", "tool": ..., "arguments": ...}
          {"type": "tool_result", "tool": ..., "result": ..., "latency_ms": ...}
          {"type": "text_delta", "content": ...}
          {"type": "done"}
        """
        self._history.append({"role": "user", "content": user_message})
        save_message(self.session_id, "user", {"role": "user", "content": user_message})
        tools = get_tool_schemas()

        for _ in range(settings.max_tool_calls):
            response = await inference.chat(self._history, tools=tools)

            # No tool calls → stream final text response
            if not response.get("tool_calls"):
                self._history.append({"role": "assistant", "content": response["content"]})
                yield {"type": "text_delta", "content": response["content"]}
                yield {"type": "done"}
                return

            # Append assistant message with tool_calls
            self._history.append({
                "role": "assistant",
                "content": response["content"],
                "tool_calls": response["tool_calls"],
            })
            save_message(self.session_id, "assistant", self._history[-1])

            # Dispatch each tool call
            for tc in response["tool_calls"]:
                tool_name = tc["function"]["name"]
                try:
                    arguments = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    arguments = {}

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

                # Append tool result to history
                self._history.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result.get("result") or result.get("error")),
                })
                save_message(self.session_id, "tool", self._history[-1])

        # Exceeded max tool calls — ask LLM to synthesize with what it has
        final = await inference.chat(self._history, tools=None)
        self._history.append({"role": "assistant", "content": final["content"]})
        save_message(self.session_id, "assistant", self._history[-1])
        yield {"type": "text_delta", "content": final["content"]}
        yield {"type": "done"}

    @property
    def history(self) -> list[dict]:
        return [m for m in self._history if m["role"] != "system"]
