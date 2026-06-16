"""agent.run 单元测试（chap04 ReAct 循环 + chap06 权限集成）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from nuocode.agent import (
    MAX_ITERATIONS,
    MAX_UNKNOWN_RUN,
    NOTICE_MAX_ITER,
    NOTICE_UNKNOWN_TOOLS,
    PLAN_REMINDER_INTERVAL,
    Agent,
    ApprovalRequest,
    Mode,
    Phase,
)
from nuocode.conversation import Conversation
from nuocode.llm import Message, Request, StreamEvent, ToolCall, ToolDefinition
from nuocode.llm import Usage as LLMUsage
from nuocode.permission import Outcome, new_engine
from nuocode.tool import Registry, Result

# ───────── 工具/Provider Fakes ─────────


def _engine(tmp_path):
    e, err = new_engine(str(tmp_path))
    assert err is None
    return e


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


async def test_multi_round_loop(tmp_path: Path) -> None:
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
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    events = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]

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


async def test_pure_text_natural_finish(tmp_path: Path) -> None:
    reg, _ = _make_registry()
    fp = FakeProvider(
        scripts=[[StreamEvent(text="hello "), StreamEvent(text="world"), StreamEvent(done=True)]]
    )
    conv = Conversation()
    conv.add_user("hi")
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    events = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]
    assert events[-1].done is True
    assert conv.messages()[-1].content == "hello world"
    assert fp.call_count == 1


# ───────── 场景 B：迭代上限 ─────────


async def test_max_iterations_cap(tmp_path: Path) -> None:
    reg, _ = _make_registry()
    fp = _AlwaysToolProvider()
    conv = Conversation()
    conv.add_user("loop")
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    events = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]
    assert fp.call_count == MAX_ITERATIONS
    notices = [ev.notice for ev in events if ev.notice]
    assert NOTICE_MAX_ITER in notices
    assert conv.last_role() == "assistant"


# ───────── 场景 C：连续未知工具 ─────────


async def test_unknown_tools_run_stops(tmp_path: Path) -> None:
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
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    events = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]
    notices = [ev.notice for ev in events if ev.notice]
    assert NOTICE_UNKNOWN_TOOLS in notices
    assert fp.call_count == MAX_UNKNOWN_RUN


async def test_unknown_run_resets_on_known_tool(tmp_path: Path) -> None:
    reg, _ = _make_registry()
    scripts: list[list[StreamEvent]] = [
        [
            StreamEvent(tool_calls=[ToolCall(id="u1", name="ghost", input="{}")]),
            StreamEvent(done=True),
        ],
        [
            StreamEvent(tool_calls=[ToolCall(id="r1", name="read_file", input="{}")]),
            StreamEvent(done=True),
        ],
        [
            StreamEvent(tool_calls=[ToolCall(id="u2", name="ghost", input="{}")]),
            StreamEvent(done=True),
        ],
        [StreamEvent(text="done"), StreamEvent(done=True)],
    ]
    fp = FakeProvider(scripts=scripts)
    conv = Conversation()
    conv.add_user("mix")
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    events = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]
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


async def test_concurrent_batch_then_serial(tmp_path: Path) -> None:
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
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    _ = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]

    assert peak.get("max", 0) >= 2
    assert started and started[0] - t0 >= 0.04

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


async def test_cancel_keeps_history_consistent(tmp_path: Path) -> None:
    reg = Registry()
    reg.register(_BlockingTool(asyncio.Event()))
    call = ToolCall(id="b1", name="block", input="{}")
    fp = FakeProvider(scripts=[[StreamEvent(tool_calls=[call]), StreamEvent(done=True)]])
    conv = Conversation()
    conv.add_user("go")
    cancel = asyncio.Event()

    async def runner():
        agent = Agent(fp, reg, "v0", _engine(tmp_path))
        return [ev async for ev in agent.run(conv, Mode.BYPASS, cancel)]

    task = asyncio.create_task(runner())
    await asyncio.sleep(0.05)
    cancel.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert conv.last_role() == "assistant"
    msgs = conv.messages()
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


async def test_plan_mode_only_readonly_tools(tmp_path: Path) -> None:
    reg = Registry()
    reg.register(_NoopTool("read_file"))
    reg.register(_RW())
    fp = FakeProvider(scripts=[[StreamEvent(text="计划如下：…"), StreamEvent(done=True)]])
    conv = Conversation()
    conv.add_user("plan it")
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    _ = [ev async for ev in agent.run(conv, Mode.PLAN, asyncio.Event())]
    assert "<system-reminder>" in fp.captured_reminders[0]
    assert "计划模式" in fp.captured_reminders[0]
    names = [t.name for t in fp.captured_tools[0]]
    assert names == ["read_file"]


# ───────── 流出错 ─────────


async def test_stream_error_recovers(tmp_path: Path) -> None:
    reg, _ = _make_registry()
    fp = FakeProvider(scripts=[[StreamEvent(err=RuntimeError("boom"))]])
    conv = Conversation()
    conv.add_user("hi")
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    events = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]
    errs = [ev for ev in events if ev.err is not None]
    assert errs and isinstance(errs[0].err, RuntimeError)
    assert conv.last_role() == "assistant"


# ───────── chap05：系统提示装配 / 按轮次 reminder / 缓存用量透传 ─────────


async def test_request_carries_system_blocks(tmp_path: Path) -> None:
    reg, _ = _make_registry()
    fp = FakeProvider(scripts=[[StreamEvent(text="ok"), StreamEvent(done=True)]])
    conv = Conversation()
    conv.add_user("hello")
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    _ = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]
    req = fp.captured_reqs[0]
    assert req.system.stable
    assert req.system.environment
    assert all("<system-reminder>" not in (m.content or "") for m in conv.messages())


async def test_stable_system_consistent_between_modes(tmp_path: Path) -> None:
    reg, _ = _make_registry()
    fp1 = FakeProvider(scripts=[[StreamEvent(text="a"), StreamEvent(done=True)]])
    conv1 = Conversation()
    conv1.add_user("x")
    _ = [
        ev
        async for ev in Agent(fp1, reg, "v0", _engine(tmp_path)).run(
            conv1, Mode.BYPASS, asyncio.Event()
        )
    ]
    fp2 = FakeProvider(scripts=[[StreamEvent(text="b"), StreamEvent(done=True)]])
    conv2 = Conversation()
    conv2.add_user("y")
    _ = [
        ev
        async for ev in Agent(fp2, reg, "v0", _engine(tmp_path)).run(
            conv2, Mode.PLAN, asyncio.Event()
        )
    ]
    assert fp1.captured_reqs[0].system.stable == fp2.captured_reqs[0].system.stable


async def test_plan_reminder_full_then_concise(tmp_path: Path) -> None:
    reg, _ = _make_registry()
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
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    _ = [ev async for ev in agent.run(conv, Mode.PLAN, asyncio.Event())]
    assert PLAN_REMINDER_INTERVAL == 4
    r1 = fp.captured_reminders[0]
    r2 = fp.captured_reminders[1]
    assert "<system-reminder>" in r1 and "<system-reminder>" in r2
    assert len(r2) < len(r1)
    assert "PLAN MODE" in r1
    assert "PLAN MODE" not in r2
    for m in conv.messages():
        assert "<system-reminder>" not in (m.content or "")


async def test_default_mode_no_reminder(tmp_path: Path) -> None:
    reg, _ = _make_registry()
    fp = FakeProvider(scripts=[[StreamEvent(text="ok"), StreamEvent(done=True)]])
    conv = Conversation()
    conv.add_user("x")
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    _ = [ev async for ev in agent.run(conv, Mode.DEFAULT, asyncio.Event())]
    assert fp.captured_reminders[0] == ""


async def test_cache_usage_propagated(tmp_path: Path) -> None:
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
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    events = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]
    usages = [e.usage for e in events if e.usage is not None]
    assert usages
    u = usages[-1]
    assert u.input == 10 and u.output == 5
    assert u.cache_write == 7 and u.cache_read == 9


# ───────── chap06：权限集成 ─────────


class _Writer:
    """通用 write_file 模拟工具：记录调用，落地到给定目录。"""

    read_only = False

    def __init__(self, root: Path) -> None:
        self._root = root
        self.calls: list[str] = []

    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return "write file"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, args: str) -> Result:
        data = json.loads(args)
        self.calls.append(args)
        return Result(content=f"wrote {data.get('path')}")


async def test_deny_outside_root_recovers(tmp_path: Path) -> None:
    """沙箱外路径 → Deny 回灌、模型可继续到下一轮。"""
    reg = Registry()
    reg.register(_Writer(tmp_path))
    bad = ToolCall(id="w1", name="write_file", input=json.dumps({"path": "/etc/x", "content": "y"}))
    fp = FakeProvider(
        scripts=[
            [StreamEvent(tool_calls=[bad]), StreamEvent(done=True)],
            [StreamEvent(text="改路径"), StreamEvent(done=True)],
        ]
    )
    conv = Conversation()
    conv.add_user("write")
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    events = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]
    end = next(e for e in events if e.tool and e.tool.phase == Phase.END)
    assert end.tool.is_error
    assert "项目目录之外" in end.tool.result
    assert events[-1].done is True
    assert fp.call_count == 2


async def test_blacklist_blocks_in_bypass(tmp_path: Path) -> None:
    """黑名单在 BYPASS 模式下仍然拦截。"""

    class _Bash:
        read_only = False

        def name(self):
            return "bash"

        def description(self):
            return "bash"

        def parameters(self):
            return {"type": "object", "properties": {"command": {"type": "string"}}}

        async def execute(self, args):
            return Result(content="ran")

    reg = Registry()
    reg.register(_Bash())
    bad = ToolCall(id="b", name="bash", input=json.dumps({"command": "rm -rf /"}))
    fp = FakeProvider(
        scripts=[
            [StreamEvent(tool_calls=[bad]), StreamEvent(done=True)],
            [StreamEvent(text="abort"), StreamEvent(done=True)],
        ]
    )
    conv = Conversation()
    conv.add_user("danger")
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    events = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]
    end = next(e for e in events if e.tool and e.tool.phase == Phase.END)
    assert end.tool.is_error
    assert "黑名单" in end.tool.result


async def test_mixed_batch_order_preserved(tmp_path: Path) -> None:
    """单批：被拒只读 + 放行只读 → 结果按调用序、ID 配对。"""

    class _ReadX:
        read_only = True

        def name(self):
            return "read_file"

        def description(self):
            return "read"

        def parameters(self):
            return {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            }

        async def execute(self, args):
            data = json.loads(args)
            return Result(content=f"content-of-{data['path']}")

    reg = Registry()
    reg.register(_ReadX())
    calls = [
        ToolCall(id="r1", name="read_file", input=json.dumps({"path": "/etc/passwd"})),
        ToolCall(id="r2", name="read_file", input=json.dumps({"path": "ok.txt"})),
    ]
    fp = FakeProvider(
        scripts=[
            [StreamEvent(tool_calls=calls), StreamEvent(done=True)],
            [StreamEvent(text="ok"), StreamEvent(done=True)],
        ]
    )
    conv = Conversation()
    conv.add_user("mix")
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    _ = [ev async for ev in agent.run(conv, Mode.BYPASS, asyncio.Event())]
    msgs = conv.messages()
    tool_msg = msgs[2]
    rs = tool_msg.tool_results
    assert [r.tool_call_id for r in rs] == ["r1", "r2"]
    assert rs[0].is_error and "项目目录之外" in rs[0].content
    assert not rs[1].is_error and "content-of-ok.txt" in rs[1].content


async def test_human_in_loop_allow_once(tmp_path: Path) -> None:
    """default 下写文件触发 ApprovalRequest，外部 set_result(ALLOW_ONCE) → 执行。"""
    reg = Registry()
    writer = _Writer(tmp_path)
    reg.register(writer)
    call = ToolCall(
        id="w1",
        name="write_file",
        input=json.dumps({"path": "a.txt", "content": "x"}),
    )
    fp = FakeProvider(
        scripts=[
            [StreamEvent(tool_calls=[call]), StreamEvent(done=True)],
            [StreamEvent(text="done"), StreamEvent(done=True)],
        ]
    )
    conv = Conversation()
    conv.add_user("write a")
    agent = Agent(fp, reg, "v0", _engine(tmp_path))

    async def consume():
        seen_approval: list[ApprovalRequest] = []
        async for ev in agent.run(conv, Mode.DEFAULT, asyncio.Event()):
            if ev.approval is not None:
                seen_approval.append(ev.approval)
                ev.approval.respond.set_result(Outcome.ALLOW_ONCE)
        return seen_approval

    seen = await asyncio.wait_for(consume(), timeout=5)
    assert len(seen) == 1
    assert writer.calls  # 已执行


async def test_human_in_loop_deny_once(tmp_path: Path) -> None:
    reg = Registry()
    writer = _Writer(tmp_path)
    reg.register(writer)
    call = ToolCall(
        id="w1",
        name="write_file",
        input=json.dumps({"path": "a.txt", "content": "x"}),
    )
    fp = FakeProvider(
        scripts=[
            [StreamEvent(tool_calls=[call]), StreamEvent(done=True)],
            [StreamEvent(text="done"), StreamEvent(done=True)],
        ]
    )
    conv = Conversation()
    conv.add_user("write")
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    events: list = []
    async for ev in agent.run(conv, Mode.DEFAULT, asyncio.Event()):
        if ev.approval is not None:
            ev.approval.respond.set_result(Outcome.DENY_ONCE)
        events.append(ev)
    end = next(e for e in events if e.tool and e.tool.phase == Phase.END)
    assert end.tool.is_error
    assert not writer.calls


async def test_human_in_loop_allow_forever_persists(tmp_path: Path) -> None:
    reg = Registry()
    writer = _Writer(tmp_path)
    reg.register(writer)
    call = ToolCall(
        id="w1",
        name="write_file",
        input=json.dumps({"path": "a.txt", "content": "x"}),
    )
    fp = FakeProvider(
        scripts=[
            [StreamEvent(tool_calls=[call]), StreamEvent(done=True)],
            [StreamEvent(text="done"), StreamEvent(done=True)],
        ]
    )
    conv = Conversation()
    conv.add_user("write")
    engine = _engine(tmp_path)
    agent = Agent(fp, reg, "v0", engine)
    async for ev in agent.run(conv, Mode.DEFAULT, asyncio.Event()):
        if ev.approval is not None:
            ev.approval.respond.set_result(Outcome.ALLOW_FOREVER)
    # 文件已写
    assert writer.calls
    # 本地配置文件含 allow 条
    local = Path(engine.local_path)
    assert local.exists()
    text = local.read_text()
    assert "Write(a.txt)" in text


async def test_readonly_batch_no_approval(tmp_path: Path) -> None:
    """一批连续只读：不产生 ApprovalRequest，仍并发完成。"""
    reg = Registry()

    class _R:
        read_only = True

        def __init__(self, n):
            self._n = n

        def name(self):
            return self._n

        def description(self):
            return self._n

        def parameters(self):
            return {"type": "object", "properties": {}, "required": []}

        async def execute(self, args):
            await asyncio.sleep(0.02)
            return Result(content=f"{self._n}-ok")

    reg.register(_R("ro1"))
    reg.register(_R("ro2"))
    calls = [
        ToolCall(id="a", name="ro1", input="{}"),
        ToolCall(id="b", name="ro2", input="{}"),
    ]
    fp = FakeProvider(
        scripts=[
            [StreamEvent(tool_calls=calls), StreamEvent(done=True)],
            [StreamEvent(text="ok"), StreamEvent(done=True)],
        ]
    )
    conv = Conversation()
    conv.add_user("ro")
    agent = Agent(fp, reg, "v0", _engine(tmp_path))
    events = [ev async for ev in agent.run(conv, Mode.DEFAULT, asyncio.Event())]
    approvals = [e for e in events if e.approval is not None]
    assert approvals == []


@pytest.mark.timeout(5)
async def test_cancel_during_approval(tmp_path: Path) -> None:
    """人在回路等待中取消 → 干净收尾、无挂起任务。"""
    reg = Registry()
    reg.register(_Writer(tmp_path))
    call = ToolCall(
        id="w1",
        name="write_file",
        input=json.dumps({"path": "x.txt", "content": "y"}),
    )
    fp = FakeProvider(scripts=[[StreamEvent(tool_calls=[call]), StreamEvent(done=True)]])
    conv = Conversation()
    conv.add_user("write")
    agent = Agent(fp, reg, "v0", _engine(tmp_path))

    pending: list[ApprovalRequest] = []

    async def runner():
        async for ev in agent.run(conv, Mode.DEFAULT, asyncio.Event()):
            if ev.approval is not None:
                pending.append(ev.approval)

    task = asyncio.create_task(runner())
    # 等待 ApprovalRequest 出现
    for _ in range(50):
        if pending:
            break
        await asyncio.sleep(0.02)
    assert pending
    # 兜底：先送 DENY_ONCE 解开 future，再取消 task
    pending[0].respond.set_result(Outcome.DENY_ONCE)
    await asyncio.wait_for(task, timeout=2)
    assert conv.last_role() == "assistant"
