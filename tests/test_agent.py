"""agent.run 单元测试（chap04 ReAct 循环）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from nuocode.agent import (
    MAX_ITERATIONS,
    MAX_UNKNOWN_RUN,
    NOTICE_MAX_ITER,
    NOTICE_UNKNOWN_TOOLS,
    PLAN_REMINDER_INTERVAL,
    Agent,
    Mode,
    Phase,
)
from nuocode.conversation import Conversation
from nuocode.llm import Message, Request, StreamEvent, ToolCall, ToolDefinition
from nuocode.llm import Usage as LLMUsage
from nuocode.tool import Registry, Result

# ───────── Fakes ─────────


class _NoopTool:
    read_only = True

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
    captured_reqs: list[Request] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        idx = self.call_count
        self.call_count += 1
        self.captured_reqs.append(req)
        events = self.scripts[idx] if idx < len(self.scripts) else [StreamEvent(done=True)]
        for ev in events:
            yield ev

    # 调用便捷访问
    @property
    def captured_msgs(self) -> list[list[Message]]:
        return [list(r.messages) for r in self.captured_reqs]

    @property
    def captured_tools(self) -> list[list[ToolDefinition]]:
        return [list(r.tools) for r in self.captured_reqs]

    @property
    def captured_reminders(self) -> list[str]:
        return [r.reminder for r in self.captured_reqs]


@dataclass
class _AlwaysToolProvider:
    """每次 stream 都返回一个 read_file 工具调用——用来触发迭代上限。"""

    call_count: int = 0
    captured_reqs: list[Request] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        idx = self.call_count
        self.call_count += 1
        self.captured_reqs.append(req)
        yield StreamEvent(tool_calls=[ToolCall(id=f"c{idx}", name="read_file", input="{}")])
        yield StreamEvent(done=True)


def _make_registry() -> tuple[Registry, _NoopTool]:
    reg = Registry()
    tool = _NoopTool("read_file", ret="file-content")
    reg.register(tool)
    return reg, tool


# ───────── 场景 A：多轮链路 ─────────


async def test_multi_round_loop() -> None:
    reg, tool = _make_registry()
    call = ToolCall(id="c1", name="read_file", input=json.dumps({"path": "x"}))
    fp = FakeProvider(
        scripts=[
            [
                StreamEvent(text="先读文件。"),
                StreamEvent(tool_calls=[call]),
                StreamEvent(done=True),
            ],
            [StreamEvent(text="读完了，结果是 file-content。"), StreamEvent(done=True)],
        ]
    )
    conv = Conversation()
    conv.add_user("read x")
    agent = Agent(fp, reg, "v0")
    events = [ev async for ev in agent.run(conv, Mode.NORMAL, asyncio.Event())]

    iters = [ev.iter for ev in events if ev.iter > 0]
    assert iters[:2] == [1, 2]
    starts = [ev for ev in events if ev.tool and ev.tool.phase == Phase.START]
    ends = [ev for ev in events if ev.tool and ev.tool.phase == Phase.END]
    assert len(starts) == 1 and len(ends) == 1
    assert ends[0].tool.result == "file-content"
    assert events[-1].done is True

    assert len(tool.calls) == 1
    msgs = conv.messages()
    assert [m.role for m in msgs] == ["user", "assistant", "tool", "assistant"]
    assert "file-content" in msgs[3].content
    assert fp.call_count == 2


async def test_pure_text_natural_finish() -> None:
    reg, _ = _make_registry()
    fp = FakeProvider(
        scripts=[[StreamEvent(text="hello "), StreamEvent(text="world"), StreamEvent(done=True)]]
    )
    conv = Conversation()
    conv.add_user("hi")
    events = [ev async for ev in Agent(fp, reg, "v0").run(conv, Mode.NORMAL, asyncio.Event())]
    assert events[-1].done is True
    assert conv.messages()[-1].content == "hello world"
    assert fp.call_count == 1


# ───────── 场景 B：迭代上限 ─────────


async def test_max_iterations_cap() -> None:
    reg, _ = _make_registry()
    fp = _AlwaysToolProvider()
    conv = Conversation()
    conv.add_user("loop")
    events = [ev async for ev in Agent(fp, reg, "v0").run(conv, Mode.NORMAL, asyncio.Event())]
    assert fp.call_count == MAX_ITERATIONS
    notices = [ev.notice for ev in events if ev.notice]
    assert NOTICE_MAX_ITER in notices
    assert conv.last_role() == "assistant"


# ───────── 场景 C：连续未知工具 ─────────


async def test_unknown_tools_run_stops() -> None:
    reg, _ = _make_registry()
    scripts: list[list[StreamEvent]] = []
    for i in range(MAX_UNKNOWN_RUN):
        scripts.append(
            [
                StreamEvent(tool_calls=[ToolCall(id=f"u{i}", name="ghost", input="{}")]),
                StreamEvent(done=True),
            ]
        )
    fp = FakeProvider(scripts=scripts)
    conv = Conversation()
    conv.add_user("call ghost")
    events = [ev async for ev in Agent(fp, reg, "v0").run(conv, Mode.NORMAL, asyncio.Event())]
    notices = [ev.notice for ev in events if ev.notice]
    assert NOTICE_UNKNOWN_TOOLS in notices
    assert fp.call_count == MAX_UNKNOWN_RUN


async def test_unknown_run_resets_on_known_tool() -> None:
    reg, _ = _make_registry()
    scripts: list[list[StreamEvent]] = [
        [
            StreamEvent(tool_calls=[ToolCall(id="u1", name="ghost", input="{}")]),
            StreamEvent(done=True),
        ],
        # 混入已知工具：计数应重置
        [
            StreamEvent(tool_calls=[ToolCall(id="r1", name="read_file", input="{}")]),
            StreamEvent(done=True),
        ],
        [
            StreamEvent(tool_calls=[ToolCall(id="u2", name="ghost", input="{}")]),
            StreamEvent(done=True),
        ],
        # 第 4 轮纯文本，应自然完成
        [StreamEvent(text="done"), StreamEvent(done=True)],
    ]
    fp = FakeProvider(scripts=scripts)
    conv = Conversation()
    conv.add_user("mix")
    events = [ev async for ev in Agent(fp, reg, "v0").run(conv, Mode.NORMAL, asyncio.Event())]
    notices = [ev.notice for ev in events if ev.notice]
    assert NOTICE_UNKNOWN_TOOLS not in notices
    assert events[-1].done is True
    assert fp.call_count == 4


# ───────── 场景 D：保序分批并发 ─────────


class _StubReadOnly:
    read_only = True

    def __init__(self, n: str, peak: dict, sleep: float = 0.05) -> None:
        self._n = n
        self._peak = peak
        self._sleep = sleep

    def name(self) -> str:
        return self._n

    def description(self) -> str:
        return self._n

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: str) -> Result:
        self._peak["cur"] = self._peak.get("cur", 0) + 1
        self._peak["max"] = max(self._peak.get("max", 0), self._peak["cur"])
        try:
            await asyncio.sleep(self._sleep)
            return Result(content=f"{self._n}-ok")
        finally:
            self._peak["cur"] -= 1


class _StubWriter:
    read_only = False

    def __init__(self, started_at: list[float]) -> None:
        self._started = started_at

    def name(self) -> str:
        return "writer"

    def description(self) -> str:
        return "writer"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: str) -> Result:
        self._started.append(asyncio.get_event_loop().time())
        return Result(content="writer-ok")


async def test_concurrent_batch_then_serial() -> None:
    reg = Registry()
    peak: dict = {}
    started: list[float] = []
    reg.register(_StubReadOnly("ro1", peak))
    reg.register(_StubReadOnly("ro2", peak))
    reg.register(_StubWriter(started))

    calls = [
        ToolCall(id="a", name="ro1", input="{}"),
        ToolCall(id="b", name="ro2", input="{}"),
        ToolCall(id="c", name="writer", input="{}"),
    ]
    fp = FakeProvider(
        scripts=[
            [StreamEvent(tool_calls=calls), StreamEvent(done=True)],
            [StreamEvent(text="done"), StreamEvent(done=True)],
        ]
    )
    conv = Conversation()
    conv.add_user("mixed")
    t0 = asyncio.get_event_loop().time()
    _ = [ev async for ev in Agent(fp, reg, "v0").run(conv, Mode.NORMAL, asyncio.Event())]

    # 两只读应并发（峰值 >=2）
    assert peak.get("max", 0) >= 2
    # writer 在两只读之后开始
    assert started and started[0] - t0 >= 0.04

    # 历史中工具结果按调用序回灌
    msgs = conv.messages()
    tool_msg = msgs[2]
    assert [r.tool_call_id for r in tool_msg.tool_results] == ["a", "b", "c"]


# ───────── 场景 E：取消历史一致 ─────────


class _BlockingTool:
    read_only = False

    def __init__(self, gate: asyncio.Event) -> None:
        self._gate = gate

    def name(self) -> str:
        return "block"

    def description(self) -> str:
        return "blocks"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: str) -> Result:
        await asyncio.sleep(0.5)
        return Result(content="never")


async def test_cancel_keeps_history_consistent() -> None:
    reg = Registry()
    reg.register(_BlockingTool(asyncio.Event()))
    call = ToolCall(id="b1", name="block", input="{}")
    fp = FakeProvider(scripts=[[StreamEvent(tool_calls=[call]), StreamEvent(done=True)]])
    conv = Conversation()
    conv.add_user("go")
    cancel = asyncio.Event()

    async def runner():
        return [ev async for ev in Agent(fp, reg, "v0").run(conv, Mode.NORMAL, cancel)]

    task = asyncio.create_task(runner())
    await asyncio.sleep(0.05)
    cancel.set()
    # 工具仍会跑完（block 是单步串行 await）；run 在串行执行完后看到 cancel 又会按取消处理
    # 这里给一点时间让 run 收尾
    await asyncio.wait_for(task, timeout=2.0)

    # 历史以 assistant 收尾
    assert conv.last_role() == "assistant"
    msgs = conv.messages()
    # 结构合法：user → assistant(tool_calls) → tool → assistant
    assert msgs[0].role == "user"
    assert msgs[1].role == "assistant" and msgs[1].tool_calls
    assert msgs[2].role == "tool"
    assert msgs[-1].role == "assistant"


# ───────── 场景 F：Plan Mode 工具集 ─────────


class _RW:
    read_only = False

    def name(self) -> str:
        return "writer"

    def description(self) -> str:
        return "writer"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: str) -> Result:
        return Result(content="ok")


async def test_plan_mode_only_readonly_tools() -> None:
    reg = Registry()
    reg.register(_NoopTool("read_file"))  # read_only = True
    reg.register(_RW())
    fp = FakeProvider(scripts=[[StreamEvent(text="计划如下：…"), StreamEvent(done=True)]])
    conv = Conversation()
    conv.add_user("plan it")
    _ = [ev async for ev in Agent(fp, reg, "v0").run(conv, Mode.PLAN, asyncio.Event())]
    assert "<system-reminder>" in fp.captured_reminders[0]
    assert "计划模式" in fp.captured_reminders[0]
    names = [t.name for t in fp.captured_tools[0]]
    assert names == ["read_file"]


# ───────── 流出错 ─────────


async def test_stream_error_recovers() -> None:
    reg, _ = _make_registry()
    fp = FakeProvider(scripts=[[StreamEvent(err=RuntimeError("boom"))]])
    conv = Conversation()
    conv.add_user("hi")
    events = [ev async for ev in Agent(fp, reg, "v0").run(conv, Mode.NORMAL, asyncio.Event())]
    errs = [ev for ev in events if ev.err is not None]
    assert errs and isinstance(errs[0].err, RuntimeError)
    assert conv.last_role() == "assistant"


# ───────── chap05：系统提示装配 / 按轮次 reminder / 缓存用量透传 ─────────


async def test_request_carries_system_blocks() -> None:
    reg, _ = _make_registry()
    fp = FakeProvider(scripts=[[StreamEvent(text="ok"), StreamEvent(done=True)]])
    conv = Conversation()
    conv.add_user("hello")
    _ = [ev async for ev in Agent(fp, reg, "v0").run(conv, Mode.NORMAL, asyncio.Event())]
    req = fp.captured_reqs[0]
    assert req.system.stable  # 稳定段非空
    assert req.system.environment  # 环境段非空
    # reminder 不写入持久历史
    assert all("<system-reminder>" not in (m.content or "") for m in conv.messages())


async def test_stable_system_consistent_between_modes() -> None:
    reg, _ = _make_registry()
    # 普通模式
    fp1 = FakeProvider(scripts=[[StreamEvent(text="a"), StreamEvent(done=True)]])
    conv1 = Conversation()
    conv1.add_user("x")
    _ = [ev async for ev in Agent(fp1, reg, "v0").run(conv1, Mode.NORMAL, asyncio.Event())]
    # 规划模式
    fp2 = FakeProvider(scripts=[[StreamEvent(text="b"), StreamEvent(done=True)]])
    conv2 = Conversation()
    conv2.add_user("y")
    _ = [ev async for ev in Agent(fp2, reg, "v0").run(conv2, Mode.PLAN, asyncio.Event())]
    assert fp1.captured_reqs[0].system.stable == fp2.captured_reqs[0].system.stable


async def test_plan_reminder_full_then_concise() -> None:
    """规划模式：iter1 完整、iter2 精简（PLAN_REMINDER_INTERVAL=4）。"""
    reg, _ = _make_registry()
    # 让循环至少跑两轮：第一轮触发已知工具，第二轮纯文本完成
    scripts: list[list[StreamEvent]] = [
        [
            StreamEvent(tool_calls=[ToolCall(id="r1", name="read_file", input="{}")]),
            StreamEvent(done=True),
        ],
        [StreamEvent(text="计划如下"), StreamEvent(done=True)],
    ]
    fp = FakeProvider(scripts=scripts)
    conv = Conversation()
    conv.add_user("plan")
    _ = [ev async for ev in Agent(fp, reg, "v0").run(conv, Mode.PLAN, asyncio.Event())]
    assert PLAN_REMINDER_INTERVAL == 4
    r1 = fp.captured_reminders[0]
    r2 = fp.captured_reminders[1]
    assert "<system-reminder>" in r1 and "<system-reminder>" in r2
    # 完整版更详细，精简版更短
    assert len(r2) < len(r1)
    # 完整版含 PLAN MODE，精简版不含
    assert "PLAN MODE" in r1
    assert "PLAN MODE" not in r2
    # reminder 不写入持久历史
    for m in conv.messages():
        assert "<system-reminder>" not in (m.content or "")


async def test_normal_mode_no_reminder() -> None:
    reg, _ = _make_registry()
    fp = FakeProvider(scripts=[[StreamEvent(text="ok"), StreamEvent(done=True)]])
    conv = Conversation()
    conv.add_user("x")
    _ = [ev async for ev in Agent(fp, reg, "v0").run(conv, Mode.NORMAL, asyncio.Event())]
    assert fp.captured_reminders[0] == ""


async def test_cache_usage_propagated() -> None:
    reg, _ = _make_registry()
    fp = FakeProvider(
        scripts=[
            [
                StreamEvent(text="hi"),
                StreamEvent(
                    usage=LLMUsage(input_tokens=10, output_tokens=5, cache_write=7, cache_read=9)
                ),
                StreamEvent(done=True),
            ]
        ]
    )
    conv = Conversation()
    conv.add_user("u")
    events = [ev async for ev in Agent(fp, reg, "v0").run(conv, Mode.NORMAL, asyncio.Event())]
    usages = [e.usage for e in events if e.usage is not None]
    assert usages
    u = usages[-1]
    assert u.input == 10 and u.output == 5
    assert u.cache_write == 7 and u.cache_read == 9
