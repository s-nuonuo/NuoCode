"""Anthropic 协议适配器。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import anthropic

from nuocode.config import ProviderConfig
from nuocode.llm import Message, StreamEvent
from nuocode.prompt import SYSTEM_PROMPT


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

    async def stream(self, msgs: list[Message]) -> AsyncIterator[StreamEvent]:
        sdk_msgs = [{"role": m.role, "content": m.content} for m in msgs]
        params: dict[str, object] = {
            "model": self._model,
            "max_tokens": 4096,
            "system": SYSTEM_PROMPT,
            "messages": sdk_msgs,
        }
        if self._thinking:
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
                        # thinking_delta / input_json_delta 等：丢弃
                    # 其它事件忽略
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            yield StreamEvent(err=e)
