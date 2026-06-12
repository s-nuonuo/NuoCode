"""LLM 协议无关层：统一消息/事件类型与 Provider Protocol。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from nuocode.config import ProviderConfig

Role = Literal["user", "assistant"]


@dataclass
class Message:
    role: Role
    content: str


@dataclass
class StreamEvent:
    text: str = ""
    done: bool = False
    err: Exception | None = None


@runtime_checkable
class Provider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    def stream(self, msgs: list[Message]) -> AsyncIterator[StreamEvent]: ...


def new_provider(cfg: ProviderConfig) -> Provider:
    """按 cfg.protocol 构造对应的适配器。"""
    if cfg.protocol == "anthropic":
        from nuocode.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg)
    if cfg.protocol == "openai":
        from nuocode.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(cfg)
    raise ValueError(f"未知协议: {cfg.protocol!r}")


__all__ = [
    "Message",
    "Provider",
    "StreamEvent",
    "new_provider",
]
