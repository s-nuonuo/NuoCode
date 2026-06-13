"""OpenAI 协议适配器（兼容端点亦适用）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import openai

from nuocode.config import ProviderConfig
from nuocode.llm import (
    ROLE_TOOL,
    Message,
    StreamEvent,
    ToolCall,
    ToolDefinition,
)
from nuocode.prompt import SYSTEM_PROMPT


def _to_openai_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def _to_openai_messages(msgs: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in msgs:
        if m.role == "user":
            out.append({"role": "user", "content": m.content})
        elif m.role == "assistant":
            if m.tool_calls:
                tc_list = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": c.input or "{}",
                        },
                    }
                    for c in m.tool_calls
                ]
                msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": m.content if m.content else None,
                    "tool_calls": tc_list,
                }
                out.append(msg)
            else:
                out.append({"role": "assistant", "content": m.content})
        elif m.role == ROLE_TOOL:
            for r in m.tool_results:
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": r.tool_call_id,
                        "content": r.content,
                    }
                )
    return out


class OpenAIProvider:
    def __init__(self, cfg: ProviderConfig) -> None:
        kwargs: dict[str, object] = {"api_key": cfg.api_key}
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        self._client = openai.AsyncOpenAI(**kwargs)  # type: ignore[arg-type]
        self._name = cfg.name
        self._model = cfg.model

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    async def stream(
        self,
        msgs: list[Message],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        messages = _to_openai_messages(msgs)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)

        # 按 index 累积工具调用分片
        tool_calls_buf: dict[int, dict[str, str]] = {}

        try:
            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                choice = choices[0]
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue

                # 文本增量
                content = getattr(delta, "content", None)
                if content:
                    yield StreamEvent(text=content)

                # 工具调用增量
                tcs = getattr(delta, "tool_calls", None) or []
                for tc in tcs:
                    idx = getattr(tc, "index", 0) or 0
                    buf = tool_calls_buf.setdefault(idx, {"id": "", "name": "", "args": ""})
                    tc_id = getattr(tc, "id", None)
                    if tc_id:
                        buf["id"] = tc_id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        n = getattr(fn, "name", None)
                        if n:
                            buf["name"] = n
                        a = getattr(fn, "arguments", None)
                        if a:
                            buf["args"] = (buf.get("args") or "") + a

            if tool_calls_buf:
                calls: list[ToolCall] = []
                for idx in sorted(tool_calls_buf.keys()):
                    v = tool_calls_buf[idx]
                    calls.append(
                        ToolCall(
                            id=v.get("id") or f"call_{idx}",
                            name=v.get("name") or "",
                            input=v.get("args") or "{}",
                        )
                    )
                yield StreamEvent(tool_calls=calls)

            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            yield StreamEvent(err=e)
