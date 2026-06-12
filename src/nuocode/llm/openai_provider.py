"""OpenAI 协议适配器（兼容端点亦适用）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import openai

from nuocode.config import ProviderConfig
from nuocode.llm import Message, StreamEvent
from nuocode.prompt import SYSTEM_PROMPT


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

    async def stream(self, msgs: list[Message]) -> AsyncIterator[StreamEvent]:
        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend({"role": m.role, "content": m.content} for m in msgs)

        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,  # type: ignore[arg-type]
                stream=True,
            )
            async for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                text = getattr(delta, "content", None) if delta is not None else None
                if text:
                    yield StreamEvent(text=text)
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            yield StreamEvent(err=e)
