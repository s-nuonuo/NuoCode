"""run_to_completion 单测（chap13 T16）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest

from nuocode.agent import MAX_ITERATIONS, Agent, ApprovalRequest, MaxTurnsReached
from nuocode.conversation import Conversation
from nuocode.llm import Request, StreamEvent, ToolCall, ToolResult
from nuocode.llm import Usage as LLMUsage
from nuocode.permission import Mode, Outcome, new_engine
from nuocode.tool import Registry, Result


# ─── Fakes ───────────────────────────────────────────────────────────────


def _engine(tmp_path):
    e, err = new_engine(str(tmp_path))
    assert err is None
    return e


class _NoopTool:
    read_only = False

    def __init__(self, n: str, ret: str = "tool-result") -> None:
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
    scripts: list[list[StreamEvent]] = field(default_factory=list)
    call_count: int = 0

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        idx = self.call_count
        self.call_count += 1
        events = self.scripts[idx] if idx < len(self.scripts) else [StreamEvent(done=True)]
        for ev in events:
            yield ev


def _text_script(*texts: str) -> list[list[StreamEvent]]:
    """生成一系列纯文本回复脚本。"""
    return [[StreamEvent(text=t), StreamEvent(done=True)] for t in texts]


def _tool_then_text(tool_name: str, tool_id: str, final: str) -> list[list[StreamEvent]]:
    """第一轮：工具调用；第二轮：纯文本。"""
    return [
        [
            StreamEvent(tool_calls=[ToolCall(id=tool_id, name=tool_name, input="{}")]),
            StreamEvent(done=True),
        ],
        [StreamEvent(text=final), StreamEvent(done=True)],
    ]


def _make_agent(provider, registry, tmp_path, **kwargs) -> Agent:
    return Agent(
        provider=provider,
        registry=registry,
        version="0.1.0",
        engine=_engine(tmp_path),
        **kwargs,
    )


# ─── 基础流程 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pure_text_returns_final(tmp_path):
    prov = FakeProvider(scripts=_text_script("hello world"))
    reg = Registry()
    agent = _make_agent(prov, reg, tmp_path)
    conv = Conversation()
    result = await agent.run_to_completion(conv, "say hello")
    assert "hello world" in result


@pytest.mark.asyncio
async def test_empty_task_no_extra_message(tmp_path):
    """task='' 时不追加 user 消息，但 conv 已有消息时正常跑。"""
    prov = FakeProvider(scripts=_text_script("ok"))
    reg = Registry()
    agent = _make_agent(prov, reg, tmp_path)
    conv = Conversation()
    conv.add_user("pre-existing message")
    result = await agent.run_to_completion(conv, "")
    assert result


@pytest.mark.asyncio
async def test_tool_call_executed_and_final_text(tmp_path):
    """工具调用被执行，最终返回文本。"""
    prov = FakeProvider(scripts=_tool_then_text("mytool", "c1", "done"))
    reg = Registry()

    executed = []

    class _MyTool:
        read_only = True
        is_system = False
        def name(self): return "mytool"
        def description(self): return "mytool"
        def parameters(self): return {"type": "object", "properties": {}, "required": []}
        async def execute(self, args):
            executed.append(args)
            return Result(content="tool-ok")

    reg.register(_MyTool())
    # BYPASS 模式跳过权限决策，确保工具被执行
    from nuocode.permission import Mode as PMode
    agent = _make_agent(prov, reg, tmp_path, permission_mode=PMode.BYPASS)
    conv = Conversation()
    result = await agent.run_to_completion(conv, "use mytool")
    assert "done" in result
    assert len(executed) == 1


@pytest.mark.asyncio
async def test_max_turns_raises(tmp_path):
    """模型一直调工具不出文本，触达 max_turns=2 时 raise MaxTurnsReached。"""
    # 每一轮都返回工具调用（使用只读工具以避免 approval 阻塞）
    always_tool_script: list[list[StreamEvent]] = []
    for _ in range(10):  # 足够多的脚本
        always_tool_script.append([
            StreamEvent(tool_calls=[ToolCall(id="c1", name="read_file", input="{}")]),
            StreamEvent(done=True),
        ])
    prov = FakeProvider(scripts=always_tool_script)
    reg = Registry()
    # 只读工具不需要 approval
    class _ReadTool:
        read_only = True
        def name(self): return "read_file"
        def description(self): return "read"
        def parameters(self): return {"type": "object", "properties": {}, "required": []}
        async def execute(self, args): return Result(content="file content")
    reg.register(_ReadTool())
    agent = _make_agent(prov, reg, tmp_path, max_turns=2)
    conv = Conversation()
    with pytest.raises(MaxTurnsReached):
        await agent.run_to_completion(conv, "loop forever")


# ─── dont_ask 短路 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dont_ask_allows_exec_tool(tmp_path):
    """dont_ask=True 时，Ask 级工具直接放行，不弹 approval。"""
    prov = FakeProvider(scripts=_tool_then_text("bash", "c1", "executed"))
    reg = Registry()

    class _BashTool:
        read_only = False
        def name(self): return "bash"
        def description(self): return "bash"
        def parameters(self): return {"type": "object", "properties": {}, "required": []}
        async def execute(self, args): return Result(content="executed")

    tool = _BashTool()
    reg.register(tool)

    # dont_ask=True 且用 BYPASS 权限引擎（确保权限允许）
    from nuocode.permission import Mode
    agent = _make_agent(prov, reg, tmp_path, dont_ask=True, permission_mode=Mode.BYPASS)
    conv = Conversation()
    result = await agent.run_to_completion(conv, "run bash")
    assert "executed" in result


@pytest.mark.asyncio
async def test_dont_ask_bypasses_ask_decision(tmp_path):
    """dont_ask=True 时，Ask 决策被转为 Allow（直接执行工具无需用户响应）。"""
    prov = FakeProvider(scripts=_tool_then_text("bash", "c1", "auto-allowed"))
    reg = Registry()

    class _BashTool:
        read_only = False
        def name(self): return "bash"
        def description(self): return "bash"
        def parameters(self): return {"type": "object", "properties": {}, "required": []}
        async def execute(self, args): return Result(content="auto-allowed")

    reg.register(_BashTool())
    # DEFAULT mode 下 bash 会 Ask；dont_ask=True 应直接放行
    agent = _make_agent(prov, reg, tmp_path, dont_ask=True)
    conv = Conversation()
    result = await agent.run_to_completion(conv, "run bash")
    # 如果 dont_ask 生效则工具被执行，不会卡在 approval
    assert "auto-allowed" in result


# ─── approval_upgrader 回调 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approval_upgrader_called(tmp_path):
    """设了 approval_upgrader 时，Ask 决策触发回调。"""
    prov = FakeProvider(scripts=_tool_then_text("bash", "c1", "ran"))
    reg = Registry()

    class _BashTool:
        read_only = False
        def name(self): return "bash"
        def description(self): return "bash"
        def parameters(self): return {"type": "object", "properties": {}, "required": []}
        async def execute(self, args): return Result(content="ran")

    reg.register(_BashTool())

    upgrader_calls: list = []

    async def mock_upgrader(req: ApprovalRequest):
        upgrader_calls.append(req.name)
        return (Outcome.ALLOW_ONCE, True)

    agent = _make_agent(prov, reg, tmp_path, approval_upgrader=mock_upgrader)
    conv = Conversation()
    result = await agent.run_to_completion(conv, "run bash")
    assert "ran" in result
    assert "bash" in upgrader_calls


# ─── events 队列转发 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_events_queue_receives_events(tmp_path):
    prov = FakeProvider(scripts=_text_script("event text"))
    reg = Registry()
    agent = _make_agent(prov, reg, tmp_path)
    conv = Conversation()
    events: asyncio.Queue = asyncio.Queue()
    result = await agent.run_to_completion(conv, "task", events=events)
    assert result
    collected = []
    while not events.empty():
        collected.append(await events.get())
    # 应有迭代和文本事件
    assert any(getattr(e, "text", "") for e in collected)


# ─── allowed_tools 过滤 ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_allowed_tools_filter(tmp_path):
    """子 Agent 的 allowed_tools 限制工具可见性。"""
    prov = FakeProvider(scripts=_tool_then_text("read_file", "c1", "ok"))
    reg = Registry()

    class _ReadTool:
        read_only = True
        def name(self): return "read_file"
        def description(self): return "read_file"
        def parameters(self): return {"type": "object", "properties": {}, "required": []}
        async def execute(self, args): return Result(content="file content")

    class _WriteTool:
        read_only = False
        def name(self): return "write_file"
        def description(self): return "write_file"
        def parameters(self): return {"type": "object", "properties": {}, "required": []}
        async def execute(self, args): return Result(content="written")

    reg.register(_ReadTool())
    reg.register(_WriteTool())
    agent = _make_agent(prov, reg, tmp_path, allowed_tools=["read_file"])
    conv = Conversation()
    result = await agent.run_to_completion(conv, "read a file")
    assert result
