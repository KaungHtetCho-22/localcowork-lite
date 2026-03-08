"""
Inference client — thin wrapper around OpenAI-compatible API.
Works with llama.cpp server, Ollama, or vLLM without code changes.
"""
from __future__ import annotations

import json
from typing import AsyncIterator, Any
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from backend.config import settings


class InferenceClient:
    def __init__(self):
        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key="not-needed",  # llama.cpp doesn't require a key
        )

    async def chat(
        self,
        messages: list[ChatCompletionMessageParam],
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> dict:
        """Single-turn completion. Returns the full message dict."""
        kwargs: dict[str, Any] = dict(
            model=settings.llm_model,
            messages=messages,
            temperature=settings.llm_temperature,
            top_p=settings.llm_top_p,
            max_tokens=settings.llm_max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await self._client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        return {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in (msg.tool_calls or [])
            ],
        }

    async def stream_chat(
        self,
        messages: list[ChatCompletionMessageParam],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """Streaming completion — yields text deltas."""
        kwargs: dict[str, Any] = dict(
            model=settings.llm_model,
            messages=messages,
            temperature=settings.llm_temperature,
            top_p=settings.llm_top_p,
            max_tokens=settings.llm_max_tokens,
            stream=True,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        async for chunk in await self._client.chat.completions.create(**kwargs):
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    async def health(self) -> bool:
        """Check if the model server is reachable."""
        try:
            models = await self._client.models.list()
            return len(models.data) > 0
        except Exception:
            return False


# Singleton
inference = InferenceClient()
