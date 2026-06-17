"""LLM 协议无关层：统一消息/事件/工具类型与 Provider Protocol。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from nuocode.config import ProviderConfig

# ───────── 角色常量 ─────────

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"  # 携带工具执行结果的回合

Role = Literal["user", "assistant", "tool"]


# ───────── 错误 ─────────


class PromptTooLongError(Exception):
    """provider 层把"上下文超长"统一抛出的协议无关错误。

    各适配器在捕获到协议特异的"prompt too long"错误时，包装成本类型再抛
    （或通过 ``StreamEvent.err`` 投递）。compact 包据此判定是否进入紧急路径。
    """

    def __init__(self, message: str = "prompt too long", *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


# ───────── 工具相关类型 ─────────


@dataclass
class ToolCall:
    """协议无关地承载模型发起的一次工具调用（流式拼接完成后）。"""

    id: str
    name: str
    input: str  # 拼接完成的 JSON 参数字符串（raw JSON）


@dataclass
class ToolResult:
    """协议无关地承载一次工具执行结果。"""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class ToolDefinition:
    """注册中心导出的协议无关工具定义。"""

    name: str
    description: str
    input_schema: dict[str, Any]


# ───────── 消息与流事件 ─────────


@dataclass
class Message:
    """对话消息。

    - 普通 user / assistant 文本回合：``role`` + ``content``。
    - assistant 工具调用回合：``content`` 为 preamble，``tool_calls`` 非空。
    - ROLE_TOOL 回合：``tool_results`` 非空，``content`` 一般为空。
    """

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class Usage:
    """协议无关地承载一轮请求的 token 用量。

    - ``input_tokens``：本轮请求输入（含完整历史）token 数。
    - ``output_tokens``：本轮响应输出 token 数。
    - ``cache_write``：本轮写入缓存的 token 数（Anthropic：``cache_creation_input_tokens``；
      OpenAI 自动缓存无写计数 → 恒 0）。
    - ``cache_read``：本轮命中缓存复用的 token 数
      （Anthropic：``cache_read_input_tokens``；OpenAI：``prompt_tokens_details.cached_tokens``）。
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_write: int = 0
    cache_read: int = 0


@dataclass
class StreamEvent:
    """流式事件（多态：文本增量 / 工具调用 / 用量 / 正常结束 / 错误）。

    ``usage`` 非空：本轮 token 用量，由适配器在 ``done`` 之前一次性发出。
    """

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage | None = None
    done: bool = False
    err: Exception | None = None


# ───────── 系统提示与请求载体（chap05） ─────────


@dataclass
class System:
    """系统提示双通道载体。

    - ``stable``：可缓存的稳定系统提示（装配自固定模块，跨轮逐字节稳定）。
    - ``environment``：不缓存的环境信息段（每轮可能变化，独立第二段）。
    """

    stable: str = ""
    environment: str = ""


@dataclass
class Request:
    """一次 ``Provider.stream`` 请求的全部入参载体。"""

    messages: list[Message] = field(default_factory=list)
    tools: list[ToolDefinition] = field(default_factory=list)
    system: System = field(default_factory=System)
    reminder: str = ""  # 本轮 system-reminder 文本（已含标签；空=不注入；不写入持久历史）


# ───────── Provider Protocol ─────────


@runtime_checkable
class Provider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        """发起一轮流式对话。

        ``req`` 承载消息历史、工具集、系统提示双通道（稳定/环境）与本轮 reminder。
        """
        ...


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
    "ROLE_ASSISTANT",
    "ROLE_TOOL",
    "ROLE_USER",
    "Message",
    "PromptTooLongError",
    "Provider",
    "Request",
    "Role",
    "StreamEvent",
    "System",
    "ToolCall",
    "ToolDefinition",
    "ToolResult",
    "Usage",
    "new_provider",
]
