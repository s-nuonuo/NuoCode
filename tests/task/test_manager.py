"""task.Manager + 4 个工具的单测（chap13 T19-T24）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from nuocode.agent import Agent, MaxTurnsReached
from nuocode.conversation import Conversation
from nuocode.llm import Request, StreamEvent
from nuocode.permission import new_engine
from nuocode.task import BackgroundTask, Manager
from nuocode.task.manager import STATUS_CANCELLED, STATUS_COMPLETED, STATUS_FAILED, STATUS_RUNNING
from nuocode.task.tools import SendMessageTool, TaskGetTool, TaskListTool, TaskStopTool
from nuocode.tool import Registry, Result


# ─── Fakes ───────────────────────────────────────────────────────────────────


@dataclass
class FakeProvider:
    scripts: list[list[StreamEvent]] = field(default_factory=list)
    call_count: int = 0

    @property
    def name(self): return "fake"

    @property
    def model(self): return "fake-model"

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        idx = self.call_count
        self.call_count += 1
        events = self.scripts[idx] if idx < len(self.scripts) else [StreamEvent(done=True)]
        for ev in events:
            yield ev


def _text_scripts(*texts: str) -> list[list[StreamEvent]]:
    return [[StreamEvent(text=t), StreamEvent(done=True)] for t in texts]


def _make_agent(text: str, tmp_path) -> Agent:
    prov = FakeProvider(scripts=_text_scripts(text))
    reg = Registry()
    e, _ = new_engine(str(tmp_path))
    return Agent(provider=prov, registry=reg, version="0.1", engine=e)


# ─── Manager.launch ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_launch_returns_task_id(tmp_path):
    mgr = Manager()
    agent = _make_agent("done", tmp_path)
    conv = Conversation()
    task_id = await mgr.launch(sub_agent=agent, conv=conv, task="do it")
    assert isinstance(task_id, str)
    assert len(task_id) == 12


@pytest.mark.asyncio
async def test_launch_completes(tmp_path):
    mgr = Manager()
    agent = _make_agent("finished", tmp_path)
    conv = Conversation()
    task_id = await mgr.launch(sub_agent=agent, conv=conv, task="do it")
    # 等待任务完成
    bg = mgr.get(task_id)
    assert bg is not None
    await asyncio.sleep(0.1)  # 让 asyncio 调度运行
    assert bg.status == STATUS_COMPLETED
    assert "finished" in bg.result


@pytest.mark.asyncio
async def test_launch_with_name(tmp_path):
    mgr = Manager()
    agent = _make_agent("done", tmp_path)
    conv = Conversation()
    task_id = await mgr.launch(sub_agent=agent, conv=conv, task="t", name="my-task")
    found = mgr.find_by_name("my-task")
    assert found is not None
    assert found.id == task_id


# ─── Manager.stop ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_nonexistent_returns_false(tmp_path):
    mgr = Manager()
    assert not mgr.stop("no-such-id")


@pytest.mark.asyncio
async def test_stop_running_task(tmp_path):
    """stop 后任务 status 变 cancelled。"""
    # 让 agent 跑一个耗时任务
    async def _slow_stream(req):
        await asyncio.sleep(10)
        yield StreamEvent(text="done", done=True)

    class SlowProv:
        @property
        def name(self): return "slow"
        @property
        def model(self): return "slow-model"
        async def stream(self, req):
            await asyncio.sleep(10)
            yield StreamEvent(done=True)

    reg = Registry()
    e, _ = new_engine(str(tmp_path))
    agent = Agent(provider=SlowProv(), registry=reg, version="0.1", engine=e)
    conv = Conversation()
    conv.add_user("initial")

    mgr = Manager()
    task_id = await mgr.launch(sub_agent=agent, conv=conv, task="")
    await asyncio.sleep(0.05)  # 让任务开始
    mgr.stop(task_id)
    await asyncio.sleep(0.1)
    bg = mgr.get(task_id)
    assert bg.status == STATUS_CANCELLED


# ─── Manager.subscribe_done ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscribe_done_receives_id(tmp_path):
    mgr = Manager()
    q = mgr.subscribe_done()
    agent = _make_agent("done", tmp_path)
    conv = Conversation()
    task_id = await mgr.launch(sub_agent=agent, conv=conv, task="t")
    # 等待任务完成并推到队列
    received = await asyncio.wait_for(q.get(), timeout=3.0)
    assert received == task_id


# ─── Manager.list ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_returns_running_tasks(tmp_path):
    mgr = Manager()
    agent = _make_agent("done", tmp_path)
    conv = Conversation()
    task_id = await mgr.launch(sub_agent=agent, conv=conv, task="t")
    tasks = mgr.list()
    assert any(t.id == task_id for t in tasks)


# ─── BackgroundTask 属性 ──────────────────────────────────────────────────────


def test_is_terminal():
    bg = BackgroundTask(id="x", name=None, sub_agent=None, conv=None, task="t")
    bg.status = STATUS_RUNNING
    assert not bg.is_terminal
    bg.status = STATUS_COMPLETED
    assert bg.is_terminal
    bg.status = STATUS_FAILED
    assert bg.is_terminal
    bg.status = STATUS_CANCELLED
    assert bg.is_terminal


# ─── TaskList 工具 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_task_list_tool_empty(tmp_path):
    mgr = Manager()
    tool = TaskListTool(mgr)
    result = await tool.execute("{}")
    data = json.loads(result.content)
    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.asyncio
async def test_task_list_tool_has_running(tmp_path):
    """launch 一个正在跑的任务，TaskList 能看到。"""
    async def _slow():
        await asyncio.sleep(10)
        yield StreamEvent(done=True)

    class SlowProv:
        @property
        def name(self): return "s"
        @property
        def model(self): return "s"
        async def stream(self, req):
            await asyncio.sleep(10)
            yield StreamEvent(done=True)

    reg = Registry()
    e, _ = new_engine(str(tmp_path))
    agent = Agent(provider=SlowProv(), registry=reg, version="0.1", engine=e)
    conv = Conversation()
    conv.add_user("init")
    mgr = Manager()
    task_id = await mgr.launch(sub_agent=agent, conv=conv, task="")
    await asyncio.sleep(0.05)

    tool = TaskListTool(mgr)
    result = await tool.execute("{}")
    data = json.loads(result.content)
    assert any(t["id"] == task_id for t in data)

    mgr.stop(task_id)


# ─── TaskGet 工具 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_task_get_not_found(tmp_path):
    mgr = Manager()
    tool = TaskGetTool(mgr)
    result = await tool.execute(json.dumps({"task_id": "nope"}))
    assert result.is_error


@pytest.mark.asyncio
async def test_task_get_found(tmp_path):
    mgr = Manager()
    agent = _make_agent("answer", tmp_path)
    conv = Conversation()
    task_id = await mgr.launch(sub_agent=agent, conv=conv, task="q")
    await asyncio.sleep(0.1)  # 等完成
    tool = TaskGetTool(mgr)
    result = await tool.execute(json.dumps({"task_id": task_id}))
    assert not result.is_error
    data = json.loads(result.content)
    assert data["id"] == task_id


# ─── TaskStop 工具 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_task_stop_not_found(tmp_path):
    mgr = Manager()
    tool = TaskStopTool(mgr)
    result = await tool.execute(json.dumps({"task_id": "nope"}))
    assert result.is_error


@pytest.mark.asyncio
async def test_task_stop_success(tmp_path):
    """stop 一个已完成的任务也返回 cancellation_requested。"""
    mgr = Manager()
    agent = _make_agent("done", tmp_path)
    conv = Conversation()
    task_id = await mgr.launch(sub_agent=agent, conv=conv, task="t")
    await asyncio.sleep(0.1)

    tool = TaskStopTool(mgr)
    result = await tool.execute(json.dumps({"task_id": task_id}))
    assert not result.is_error
    data = json.loads(result.content)
    assert data["status"] == "cancellation_requested"


# ─── SendMessage 工具 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_message_not_found(tmp_path):
    mgr = Manager()
    tool = SendMessageTool(mgr)
    result = await tool.execute(json.dumps({"name": "ghost", "message": "hello"}))
    assert result.is_error


@pytest.mark.asyncio
async def test_send_message_success(tmp_path):
    """已完成的命名任务可以接收新消息。"""
    prov = FakeProvider(scripts=_text_scripts("first done", "second done"))
    reg = Registry()
    e, _ = new_engine(str(tmp_path))
    agent = Agent(provider=prov, registry=reg, version="0.1", engine=e)
    conv = Conversation()

    mgr = Manager()
    task_id = await mgr.launch(sub_agent=agent, conv=conv, task="first task", name="worker")
    await asyncio.sleep(0.2)

    assert mgr.get(task_id).status == STATUS_COMPLETED

    tool = SendMessageTool(mgr)
    result = await tool.execute(json.dumps({"name": "worker", "message": "second task"}))
    assert not result.is_error
    data = json.loads(result.content)
    assert data["status"] == "async_launched"
    assert data["name"] == "worker"
