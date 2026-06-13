"""agent.run 单元测试：用 FakeProvider 覆盖 AC8（单轮闭环）+ AC9（单轮上限）。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from nuocode.agent import Agent, Phase
from nuocode.conversation import Conversation
from nuocode.llm import Message, StreamEvent, ToolCall, ToolDefinition
from nuocode.tool import Registry, Result

# ───────── Fakes ─────────


class _NoopTool:
    def __init__(self, n: str, ret: str = "ok") -> None:
        self._n = n
        self._ret = ret
        self.calls: list[str] = []

    def name(self) -> str:
        return self._n

    def description(self) -> str:
        return f"{self._n} tool"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: str) -> Result:
        self.calls.append(args)
        return Result(content=self._ret)


@dataclass
class FakeProvider:
    """按调用次数切换脚本：每次 stream 吐出 scripts[call_count] 序列。"""

    scripts: list[list[StreamEvent]] = field(default_factory=list)
    call_count: int = 0
    captured_msgs: list[list[Message]] = field(default_factory=list)
    captured_tools: list[list[ToolDefinition]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(
        self, msgs: list[Message], tools: list[ToolDefinition]
    ) -> AsyncIterator[StreamEvent]:
        idx = self.call_count
        self.call_count += 1
        self.captured_msgs.append(list(msgs))
        self.captured_tools.append(list(tools))
        events = self.scripts[idx] if idx < len(self.scripts) else [StreamEvent(done=True)]
        for ev in events:
            yield ev


def _make_registry() -> tuple[Registry, _NoopTool]:
    reg = Registry()
    tool = _NoopTool("read_file", ret="file-content")
    reg.register(tool)
    return reg, tool


# ───────── 测试 ─────────


async def test_pure_text_turn() -> None:
    reg, _ = _make_registry()
    fp = FakeProvider(
        scripts=[
            [StreamEvent(text="hello "), StreamEvent(text="world"), StreamEvent(done=True)],
        ]
    )
    conv = Conversation()
    conv.add_user("hi")
    agent = Agent(fp, reg)
    events = [ev async for ev in agent.run(conv)]
    texts = [ev.text for ev in events if ev.text]
    assert "hello " in texts and "world" in texts
    assert events[-1].done
    msgs = conv.messages()
    assert msgs[-1].role == "assistant"
    assert msgs[-1].content == "hello world"
    # 只发起 1 次请求
    assert fp.call_count == 1


async def test_single_round_tool_loop() -> None:
    """AC8：调用工具 → 回灌 → 续答最终文本。"""
    reg, tool = _make_registry()
    call = ToolCall(id="c1", name="read_file", input=json.dumps({"path": "x"}))
    fp = FakeProvider(
        scripts=[
            # 请求#1：preamble + 一个工具调用
            [
                StreamEvent(text="我先读文件。"),
                StreamEvent(tool_calls=[call]),
                StreamEvent(done=True),
            ],
            # 请求#2：最终文本
            [
                StreamEvent(text="文件内容是 file-content。"),
                StreamEvent(done=True),
            ],
        ]
    )
    conv = Conversation()
    conv.add_user("read x")
    agent = Agent(fp, reg)
    events = [ev async for ev in agent.run(conv)]

    # 工具事件 START + END 各一次
    starts = [ev for ev in events if ev.tool and ev.tool.phase == Phase.START]
    ends = [ev for ev in events if ev.tool and ev.tool.phase == Phase.END]
    assert len(starts) == 1 and starts[0].tool.name == "read_file"
    assert len(ends) == 1 and ends[0].tool.result == "file-content"

    # 工具被执行了恰好 1 次
    assert len(tool.calls) == 1

    # 历史顺序：user → assistant(tool_calls) → tool → assistant(final)
    msgs = conv.messages()
    assert [m.role for m in msgs] == ["user", "assistant", "tool", "assistant"]
    assert msgs[1].tool_calls[0].name == "read_file"
    assert msgs[2].tool_results[0].content == "file-content"
    assert "file-content" in msgs[3].content

    # 请求被发起 2 次（请求#1 + 续答）
    assert fp.call_count == 2
    # 续答请求带工具定义
    assert len(fp.captured_tools[1]) == 1


async def test_single_round_cap_ignores_second_tool_calls() -> None:
    """AC9：续答即使返回 tool_calls 也不再触发执行。"""
    reg, tool = _make_registry()
    call1 = ToolCall(id="c1", name="read_file", input="{}")
    call2 = ToolCall(id="c2", name="read_file", input="{}")
    fp = FakeProvider(
        scripts=[
            [StreamEvent(tool_calls=[call1]), StreamEvent(done=True)],
            # 续答又请求一次工具——必须被忽略
            [StreamEvent(tool_calls=[call2]), StreamEvent(done=True)],
        ]
    )
    conv = Conversation()
    conv.add_user("go")
    agent = Agent(fp, reg)
    _ = [ev async for ev in agent.run(conv)]

    # 只执行了一次（来自请求#1 的 c1）
    assert len(tool.calls) == 1
    # provider.stream 只被调用 2 次（不会出现请求#3）
    assert fp.call_count == 2


async def test_tool_error_is_routed_as_event_and_back() -> None:
    """工具失败：is_error 在 ToolEvent 与 ToolResult 中保持。"""

    class _ErrTool:
        def name(self) -> str:
            return "boom"

        def description(self) -> str:
            return "always fails"

        def parameters(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}, "required": []}

        async def execute(self, args: str) -> Result:
            return Result(content="炸了", is_error=True)

    reg = Registry()
    reg.register(_ErrTool())

    call = ToolCall(id="c1", name="boom", input="{}")
    fp = FakeProvider(
        scripts=[
            [StreamEvent(tool_calls=[call]), StreamEvent(done=True)],
            [StreamEvent(text="已知晓错误"), StreamEvent(done=True)],
        ]
    )
    conv = Conversation()
    conv.add_user("trigger")
    events = [ev async for ev in Agent(fp, reg).run(conv)]
    end = next(ev for ev in events if ev.tool and ev.tool.phase == Phase.END)
    assert end.tool.is_error is True
    assert conv.messages()[2].tool_results[0].is_error is True
