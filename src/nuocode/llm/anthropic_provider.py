"""Anthropic 协议适配器。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from nuocode.config import ProviderConfig
from nuocode.llm import (
    ROLE_TOOL,
    Message,
    StreamEvent,
    ToolCall,
    ToolDefinition,
    Usage,
)
from nuocode.prompt import SYSTEM_PROMPT


def _to_anthropic_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]


def _to_anthropic_messages(msgs: list[Message]) -> list[dict[str, Any]]:
    """把内部 Message 列表转成 Anthropic SDK 入参格式。"""
    out: list[dict[str, Any]] = []
    for m in msgs:
        if m.role == "user":
            out.append({"role": "user", "content": m.content})
        elif m.role == "assistant":
            if m.tool_calls:
                content_blocks: list[dict[str, Any]] = []
                if m.content:
                    content_blocks.append({"type": "text", "text": m.content})
                for c in m.tool_calls:
                    try:
                        inp = json.loads(c.input or "{}")
                    except json.JSONDecodeError:
                        inp = {}
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": c.id,
                            "name": c.name,
                            "input": inp,
                        }
                    )
                out.append({"role": "assistant", "content": content_blocks})
            else:
                out.append({"role": "assistant", "content": m.content})
        elif m.role == ROLE_TOOL:
            blocks: list[dict[str, Any]] = []
            for r in m.tool_results:
                block: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": r.tool_call_id,
                    "content": r.content,
                }
                if r.is_error:
                    block["is_error"] = True
                blocks.append(block)
            out.append({"role": "user", "content": blocks})
    return out


def _has_tool_history(msgs: list[Message]) -> bool:
    for m in msgs:
        if m.role == ROLE_TOOL:
            return True
        if m.role == "assistant" and m.tool_calls:
            return True
    return False


def _effective_system(suffix: str) -> str:
    if suffix:
        return SYSTEM_PROMPT + "\n\n" + suffix
    return SYSTEM_PROMPT


class AnthropicProvider:
    def __init__(self, cfg: ProviderConfig) -> None:
        kwargs: dict[str, object] = {"api_key": cfg.api_key}
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        self._client = anthropic.AsyncAnthropic(**kwargs)  # type: ignore[arg-type]
        self._name = cfg.name
        self._model = cfg.model
        self._thinking = cfg.thinking

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
        system_suffix: str = "",
    ) -> AsyncIterator[StreamEvent]:
        sdk_msgs = _to_anthropic_messages(msgs)
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "system": _effective_system(system_suffix),
            "messages": sdk_msgs,
        }
        if tools:
            params["tools"] = _to_anthropic_tools(tools)
        # 含工具历史的请求关闭 thinking（避免缺 signature 导致 400）
        if self._thinking and not _has_tool_history(msgs):
            params["thinking"] = {"type": "enabled", "budget_tokens": 2048}

        try:
            async with self._client.messages.stream(**params) as stream:  # type: ignore[arg-type]
                async for event in stream:
                    etype = getattr(event, "type", None)
                    if etype == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        dtype = getattr(delta, "type", None)
                        if dtype == "text_delta":
                            text = getattr(delta, "text", "") or ""
                            if text:
                                yield StreamEvent(text=text)
                        # thinking_delta / input_json_delta：跳过（SDK 内部累加 input）
                    # 其它事件忽略
                final_message = await stream.get_final_message()

            if getattr(final_message, "stop_reason", None) == "tool_use":
                calls: list[ToolCall] = []
                for block in getattr(final_message, "content", []) or []:
                    btype = getattr(block, "type", None)
                    if btype == "tool_use":
                        calls.append(
                            ToolCall(
                                id=getattr(block, "id", "") or "",
                                name=getattr(block, "name", "") or "",
                                input=json.dumps(getattr(block, "input", {}) or {}),
                            )
                        )
                if calls:
                    yield StreamEvent(tool_calls=calls)
            usage = getattr(final_message, "usage", None)
            if usage is not None:
                in_tok = getattr(usage, "input_tokens", 0) or 0
                out_tok = getattr(usage, "output_tokens", 0) or 0
                yield StreamEvent(usage=Usage(input_tokens=in_tok, output_tokens=out_tok))
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            yield StreamEvent(err=e)
