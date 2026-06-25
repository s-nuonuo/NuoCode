"""AgentTool 单测（chap13 T17-T18）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nuocode.agent import Agent
from nuocode.agent.agent_tool import AgentTool
from nuocode.conversation import Conversation
from nuocode.llm import Request, StreamEvent, ToolCall
from nuocode.permission import new_engine
from nuocode.subagent.catalog import Catalog, load_catalog
from nuocode.subagent.definition import Definition, Source
from nuocode.subagent.embed import builtin_definitions
from nuocode.tool import Registry, Result


# ─── Fakes ───────────────────────────────────────────────────────────────────


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
    return [[StreamEvent(text=t), StreamEvent(done=True)] for t in texts]


def _engine(tmp_path):
    e, err = new_engine(str(tmp_path))
    assert err is None
    return e


def _make_parent_agent(prov, tmp_path) -> Agent:
    """构造一个最简父 Agent。"""
    reg = Registry()
    return Agent(
        provider=prov,
        registry=reg,
        version="0.1.0",
        engine=_engine(tmp_path),
    )


def _make_catalog_with_defs(*defs: Definition) -> Catalog:
    cat = Catalog()
    cat._add_all(list(defs))
    return cat


def _def(name: str = "test-agent", system_prompt: str = "") -> Definition:
    return Definition(
        name=name,
        description="Test agent",
        system_prompt=system_prompt,
        source=Source.BUILTIN,
    )


# ─── 基础工具接口 ─────────────────────────────────────────────────────────────


def test_name():
    prov = FakeProvider()
    parent = _make_parent_agent(prov, "/tmp")
    catalog = Catalog()
    tool = AgentTool(catalog=catalog, parent_agent=parent)
    assert tool.name() == "Agent"


def test_parameters_schema():
    prov = FakeProvider()
    parent = _make_parent_agent(prov, "/tmp")
    catalog = Catalog()
    tool = AgentTool(catalog=catalog, parent_agent=parent)
    schema = tool.parameters()
    assert "prompt" in schema["required"]
    assert "subagent_type" in schema["properties"]


# ─── 未知 subagent_type ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_subagent_type_returns_error(tmp_path):
    prov = FakeProvider()
    parent = _make_parent_agent(prov, tmp_path)
    catalog = Catalog()  # 空 catalog
    tool = AgentTool(catalog=catalog, parent_agent=parent)
    result = await tool.execute(json.dumps({
        "prompt": "do it",
        "description": "test",
        "subagent_type": "non-existent",
    }))
    assert result.is_error
    assert "未知 subagent_type" in result.content


# ─── 空 prompt 错误 ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_prompt_returns_error(tmp_path):
    prov = FakeProvider()
    parent = _make_parent_agent(prov, tmp_path)
    catalog = Catalog()
    tool = AgentTool(catalog=catalog, parent_agent=parent)
    result = await tool.execute(json.dumps({
        "prompt": "",
        "description": "test",
        "subagent_type": "explore",
    }))
    assert result.is_error
    assert "prompt" in result.content.lower()


# ─── 定义式：内联执行 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_defined_agent_inline_success(tmp_path):
    """subagent_type 非空，前台 inline 执行，返回 final_text。"""
    prov = FakeProvider(scripts=_text_script("task done"))
    parent = _make_parent_agent(prov, tmp_path)
    defn = _def("my-agent")
    catalog = _make_catalog_with_defs(defn)
    tool = AgentTool(catalog=catalog, parent_agent=parent)
    result = await tool.execute(json.dumps({
        "prompt": "do the task",
        "description": "test",
        "subagent_type": "my-agent",
    }))
    assert not result.is_error
    assert "task done" in result.content


# ─── Fork 嵌套阻断 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fork_within_fork_blocked(tmp_path):
    """对话历史里有 fork_boilerplate 时，Fork 调用被拦截。"""
    from nuocode.agent.fork import FORK_BOILERPLATE_TAG
    from nuocode.llm import Message

    prov = FakeProvider()
    parent = _make_parent_agent(prov, tmp_path)
    catalog = Catalog()

    # 构造一个包含 fork_boilerplate 标记的父对话
    parent_conv = Conversation()
    parent_conv.add_user(f"{FORK_BOILERPLATE_TAG}\nsome prior fork context</fork_boilerplate>")

    tool = AgentTool(catalog=catalog, parent_agent=parent, parent_conv=parent_conv)
    result = await tool.execute(json.dumps({
        "prompt": "nested fork task",
        "description": "test",
        # subagent_type 不传 → Fork 路径
    }))
    assert result.is_error
    assert "嵌套阻断" in result.content or "Fork" in result.content


# ─── 后台禁用时 Fork 报错 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fork_disabled_when_background_off(tmp_path):
    """enable_background=False 时 Fork 路径直接报错（N6）。"""
    prov = FakeProvider()
    parent = _make_parent_agent(prov, tmp_path)
    catalog = Catalog()
    tool = AgentTool(catalog=catalog, parent_agent=parent, enable_background=False)
    result = await tool.execute(json.dumps({
        "prompt": "fork task",
        "description": "test",
        # 不传 subagent_type → Fork
    }))
    assert result.is_error
    assert "后台" in result.content or "禁用" in result.content


# ─── 后台任务（TaskManager 存在）────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_in_background_returns_task_id(tmp_path):
    """run_in_background=True 时立刻返回 task_id。"""
    prov = FakeProvider(scripts=_text_script("bg done"))
    parent = _make_parent_agent(prov, tmp_path)
    defn = _def("bg-agent")
    catalog = _make_catalog_with_defs(defn)

    # Mock TaskManager
    class MockManager:
        async def launch(self, **kwargs):
            return "task-001"

    tool = AgentTool(
        catalog=catalog,
        parent_agent=parent,
        task_manager=MockManager(),
    )
    result = await tool.execute(json.dumps({
        "prompt": "bg task",
        "description": "test",
        "subagent_type": "bg-agent",
        "run_in_background": True,
    }))
    assert not result.is_error
    data = json.loads(result.content)
    assert data["task_id"] == "task-001"
    assert data["status"] == "async_launched"


# ─── 工具过滤（定义式，非后台）────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disallowed_tools_filtered_for_sub_agent(tmp_path):
    """disallowed_tools 列表里的工具不出现在子 Agent 的 allowed_tools 里。"""
    prov = FakeProvider(scripts=_text_script("ok"))
    parent = _make_parent_agent(prov, tmp_path)

    # 注册两个工具
    class _T1:
        read_only = True
        is_system = False
        def name(self): return "read_file"
        def description(self): return "r"
        def parameters(self): return {"type":"object","properties":{},"required":[]}
        async def execute(self, args): return Result(content="ok")

    class _T2:
        read_only = False
        is_system = False
        def name(self): return "write_file"
        def description(self): return "w"
        def parameters(self): return {"type":"object","properties":{},"required":[]}
        async def execute(self, args): return Result(content="ok")

    parent._registry.register(_T1())
    parent._registry.register(_T2())

    defn = Definition(
        name="readonly-agent",
        description="Only reads",
        disallowed_tools=["write_file"],
        source=Source.BUILTIN,
    )
    catalog = _make_catalog_with_defs(defn)
    tool = AgentTool(catalog=catalog, parent_agent=parent)

    # 计算允许工具列表
    allowed = tool._compute_allowed_tools(defn, is_background=False)
    assert "write_file" not in allowed
    # Agent 工具自身也不在（ALL_AGENT_DISALLOWED_TOOLS）
    assert "Agent" not in allowed


# ─── 内置 Catalog 集成 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_builtin_catalog_explore_agent(tmp_path):
    """使用内置 Explore 角色。"""
    prov = FakeProvider(scripts=_text_script("exploration done"))
    parent = _make_parent_agent(prov, tmp_path)
    catalog = load_catalog(str(tmp_path))
    tool = AgentTool(catalog=catalog, parent_agent=parent)
    result = await tool.execute(json.dumps({
        "prompt": "explore the codebase",
        "description": "探索",
        "subagent_type": "Explore",
    }))
    assert not result.is_error
    assert "exploration done" in result.content


# ─── JSON 解析失败 ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_json_args(tmp_path):
    prov = FakeProvider()
    parent = _make_parent_agent(prov, tmp_path)
    catalog = Catalog()
    tool = AgentTool(catalog=catalog, parent_agent=parent)
    result = await tool.execute("not-json{{{")
    assert result.is_error
