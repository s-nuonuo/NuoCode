"""TUI 单测：模式循环、待批准态按键、状态栏、模式跨轮保持。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from nuocode.config import ProviderConfig
from nuocode.llm import Request, StreamEvent, ToolCall
from nuocode.permission import Mode, Outcome, new_engine
from nuocode.tool import Registry, Result
from nuocode.tui.app import NuoCodeApp, next_mode, outcome_for_index
from nuocode.tui.view import mode_badge, status_line


def test_next_mode_cycles() -> None:
    assert next_mode(Mode.DEFAULT) == Mode.ACCEPT_EDITS
    assert next_mode(Mode.ACCEPT_EDITS) == Mode.PLAN
    assert next_mode(Mode.PLAN) == Mode.BYPASS
    assert next_mode(Mode.BYPASS) == Mode.DEFAULT


def test_outcome_for_index() -> None:
    assert outcome_for_index(0) == Outcome.ALLOW_ONCE
    assert outcome_for_index(1) == Outcome.ALLOW_FOREVER
    assert outcome_for_index(2) == Outcome.DENY_ONCE


def test_mode_badge_labels() -> None:
    assert mode_badge(Mode.DEFAULT)[0] == "DEFAULT"
    assert mode_badge(Mode.ACCEPT_EDITS)[0] == "ACCEPT EDITS"
    assert mode_badge(Mode.PLAN)[0] == "PLAN"
    assert mode_badge(Mode.BYPASS)[0] == "BYPASS"


def test_status_line_left_is_mode(tmp_path: Path) -> None:
    """状态栏左侧应是模式徽标，不再是 provider 名。"""
    rendered = status_line(Mode.BYPASS, "model-x", usage_in=0, usage_out=0)
    # 可被 rich.Table.grid 渲染，断言其包含 BYPASS 标签
    from rich.console import Console

    buf = Console(record=True, width=80, no_color=True)
    buf.print(rendered)
    out = buf.export_text()
    assert "BYPASS" in out
    assert "model-x" in out


# ───────── 用 Textual Pilot 测试交互 ─────────


@dataclass
class _FakeProvider:
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


def _make_app(tmp_path: Path) -> NuoCodeApp:
    reg = Registry()
    eng, _ = new_engine(str(tmp_path))
    cfg = ProviderConfig(
        name="fake",
        protocol="openai",
        api_key="x",
        model="fake-model",
        base_url="",
        thinking=False,
    )
    app = NuoCodeApp([cfg], reg, eng)
    return app


@pytest.mark.timeout(10)
async def test_shift_tab_cycles_mode(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        # 单 provider 自动激活，进入 idle
        await pilot.pause()
        assert app.mode == Mode.DEFAULT
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.mode == Mode.ACCEPT_EDITS
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.mode == Mode.PLAN
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.mode == Mode.BYPASS
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.mode == Mode.DEFAULT


@pytest.mark.timeout(10)
async def test_mode_persists_across_turns(tmp_path: Path, monkeypatch) -> None:
    """切到 ACCEPT_EDITS 后再 begin_turn，模式不被重置。"""

    class _WriteTool:
        read_only = False

        def name(self):
            return "noop"

        def description(self):
            return "noop"

        def parameters(self):
            return {"type": "object", "properties": {}, "required": []}

        async def execute(self, args):
            return Result(content="ok")

    reg = Registry()
    reg.register(_WriteTool())
    eng, _ = new_engine(str(tmp_path))
    cfg = ProviderConfig(
        name="fake",
        protocol="openai",
        api_key="x",
        model="m",
        base_url="",
        thinking=False,
    )
    app = NuoCodeApp([cfg], reg, eng)
    fake = _FakeProvider(scripts=[[StreamEvent(text="ok"), StreamEvent(done=True)]])

    # 用 monkeypatch 替换 new_provider 的返回值
    from nuocode.tui import app as app_mod

    monkeypatch.setattr(app_mod, "new_provider", lambda cfg: fake)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.mode == Mode.ACCEPT_EDITS
        # 跑一轮
        app.post_submit("hi")
        # 等到 idle
        for _ in range(50):
            if app.state.value == "idle":
                break
            await pilot.pause()
            await asyncio.sleep(0.02)
        assert app.mode == Mode.ACCEPT_EDITS  # 跨轮保持


@pytest.mark.timeout(10)
async def test_approval_keys_send_outcome(tmp_path: Path, monkeypatch) -> None:
    """注入 ApprovalRequest → 数字键 1/3 回传 outcome。"""

    class _Writer:
        read_only = False

        def __init__(self):
            self.calls = []

        def name(self):
            return "write_file"

        def description(self):
            return "w"

        def parameters(self):
            return {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            }

        async def execute(self, args):
            self.calls.append(args)
            return Result(content="ok")

    reg = Registry()
    reg.register(_Writer())
    eng, _ = new_engine(str(tmp_path))
    cfg = ProviderConfig(
        name="fake",
        protocol="openai",
        api_key="x",
        model="m",
        base_url="",
        thinking=False,
    )
    app = NuoCodeApp([cfg], reg, eng)
    call = ToolCall(
        id="w1",
        name="write_file",
        input=json.dumps({"path": "a.txt", "content": "x"}),
    )
    fake = _FakeProvider(
        scripts=[
            [StreamEvent(tool_calls=[call]), StreamEvent(done=True)],
            [StreamEvent(text="done"), StreamEvent(done=True)],
        ]
    )
    from nuocode.tui import app as app_mod

    monkeypatch.setattr(app_mod, "new_provider", lambda cfg: fake)

    async with app.run_test() as pilot:
        await pilot.pause()
        # default 模式 → 写文件应触发 Ask
        app.post_submit("write")
        # 等到 APPROVING 态
        for _ in range(100):
            if app.state.value == "approving":
                break
            await pilot.pause()
            await asyncio.sleep(0.02)
        assert app.state.value == "approving"
        assert app.pending is not None
        # 直接驱动按键路由（绕过 TextArea 焦点）
        assert app._update_approving("1")
        # 等到 idle
        for _ in range(100):
            if app.state.value == "idle":
                break
            await pilot.pause()
            await asyncio.sleep(0.02)
        assert app.state.value == "idle"
