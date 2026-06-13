"""Agent：单轮闭环编排。

请求#1 → 收集工具调用 → 顺序执行 → 结果回灌 → 请求#2 → 最终文本 → 停。
请求#2 即使返回 tool_calls 也忽略（单轮上限，AC9）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum

from nuocode.conversation import Conversation
from nuocode.llm import Provider, ToolCall, ToolResult
from nuocode.tool import DEFAULT_TIMEOUT, Registry


class Phase(Enum):
    START = "start"
    END = "end"


@dataclass
class ToolEvent:
    name: str
    args: str = ""
    phase: Phase = Phase.START
    result: str = ""
    is_error: bool = False


@dataclass
class Event:
    text: str = ""
    tool: ToolEvent | None = None
    done: bool = False
    err: Exception | None = None


@dataclass
class _StreamCollect:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    err: Exception | None = None


def _preview_args(s: str, limit: int = 80) -> str:
    s = s or ""
    s = s.replace("\n", " ").strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


class Agent:
    """持有 provider 与注册中心，执行单轮闭环。"""

    def __init__(self, provider: Provider, registry: Registry) -> None:
        self._provider = provider
        self._registry = registry

    async def run(self, conv: Conversation) -> AsyncIterator[Event]:
        defs = self._registry.definitions()

        # ───────── 请求#1 ─────────
        first = _StreamCollect()
        async for ev in self._provider.stream(conv.messages(), defs):
            if ev.err is not None:
                yield Event(err=ev.err)
                return
            if ev.text:
                first.text += ev.text
                yield Event(text=ev.text)
            if ev.tool_calls:
                first.tool_calls.extend(ev.tool_calls)
            if ev.done:
                break

        if not first.tool_calls:
            # 纯文本回合：直接结束
            conv.add_assistant(first.text)
            yield Event(done=True)
            return

        # 有工具调用：把 assistant 工具回合追加到历史
        conv.add_assistant_with_tool_calls(first.text, first.tool_calls)

        # ───────── 顺序执行工具 ─────────
        results: list[ToolResult] = []
        for call in first.tool_calls:
            args_preview = _preview_args(call.input)
            yield Event(tool=ToolEvent(name=call.name, args=args_preview, phase=Phase.START))
            r = await self._registry.execute(call.name, call.input, timeout=DEFAULT_TIMEOUT)
            results.append(ToolResult(tool_call_id=call.id, content=r.content, is_error=r.is_error))
            yield Event(
                tool=ToolEvent(
                    name=call.name,
                    args=args_preview,
                    phase=Phase.END,
                    result=r.content,
                    is_error=r.is_error,
                )
            )

        conv.add_tool_results(results)

        # ───────── 请求#2（续答；忽略再次的工具调用） ─────────
        second = _StreamCollect()
        async for ev in self._provider.stream(conv.messages(), defs):
            if ev.err is not None:
                yield Event(err=ev.err)
                return
            if ev.text:
                second.text += ev.text
                yield Event(text=ev.text)
            # 单轮：tool_calls 一律忽略
            if ev.done:
                break

        final = second.text
        if not final.strip():
            final = "（已完成本轮工具调用；本章为单轮闭环，不再继续触发新工具。）"
            yield Event(text=final)
        conv.add_assistant(final)
        yield Event(done=True)


__all__ = [
    "Agent",
    "Event",
    "Phase",
    "ToolEvent",
]
