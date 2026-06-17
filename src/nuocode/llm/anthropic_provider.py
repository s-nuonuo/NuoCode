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
    PromptTooLongError,
    Request,
    StreamEvent,
    ToolCall,
    ToolDefinition,
    Usage,
)


def _is_prompt_too_long(exc: Exception) -> bool:
    """Anthropic："prompt is too long" / "context length"。"""
    text = str(exc).lower()
    if "prompt is too long" in text or "context length" in text:
        return True
    # SDK BadRequestError.body 里的 error.type 也可能是 invalid_request_error
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") or {}
        msg = str(err.get("message", "")).lower()
        if "prompt is too long" in msg or "context length" in msg:
            return True
    return False


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


def _build_system_blocks(stable: str, environment: str) -> list[dict[str, Any]]:
    """构造 Anthropic system 列表：稳定块带缓存断点、环境块不带。"""
    blocks: list[dict[str, Any]] = []
    if stable:
        blocks.append(
            {
                "type": "text",
                "text": stable,
                "cache_control": {"type": "ephemeral"},
            }
        )
    if environment:
        blocks.append({"type": "text", "text": environment})
    return blocks


def _append_reminder_anthropic(messages: list[dict[str, Any]], reminder: str) -> None:
    """把 reminder 文本块追加到末条 user 消息的 content；末条非 user 时新起一条 user。"""
    if not reminder:
        return
    block = {"type": "text", "text": reminder}
    if messages and messages[-1].get("role") == "user":
        last = messages[-1]
        content = last.get("content")
        if isinstance(content, str):
            new_content: list[dict[str, Any]] = []
            if content:
                new_content.append({"type": "text", "text": content})
            new_content.append(block)
            last["content"] = new_content
        elif isinstance(content, list):
            content.append(block)
        else:
            last["content"] = [block]
    else:
        messages.append({"role": "user", "content": [block]})


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

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        sdk_msgs = _to_anthropic_messages(req.messages)
        if req.reminder:
            _append_reminder_anthropic(sdk_msgs, req.reminder)

        system_blocks = _build_system_blocks(req.system.stable, req.system.environment)

        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": sdk_msgs,
        }
        if system_blocks:
            params["system"] = system_blocks
        if req.tools:
            params["tools"] = _to_anthropic_tools(req.tools)
        # 含工具历史的请求关闭 thinking（避免缺 signature 导致 400）
        if self._thinking and not _has_tool_history(req.messages):
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
                cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
                cr = getattr(usage, "cache_read_input_tokens", 0) or 0
                yield StreamEvent(
                    usage=Usage(
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        cache_write=cw,
                        cache_read=cr,
                    )
                )
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            if _is_prompt_too_long(e):
                yield StreamEvent(err=PromptTooLongError(str(e), cause=e))
            else:
                yield StreamEvent(err=e)
