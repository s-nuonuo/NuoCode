"""test_builtin_worktree.py：/worktree 命令 handler 单测（chap14 T13）。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nuocode.command.builtin_worktree import handle_worktree
from nuocode.command.ui import WorktreeSummary


# ── 测试辅助 ───────────────────────────────────────────────────────────────


def _make_ui(accessor=None) -> MagicMock:
    """构造带 println/error/worktree_accessor 的 mock UI。"""
    ui = MagicMock()
    ui.println = MagicMock()
    ui.error = MagicMock()
    ui.worktree_accessor = MagicMock(return_value=accessor)
    return ui


def _make_accessor() -> MagicMock:
    acc = MagicMock()
    acc.create = AsyncMock(return_value=("/repo/.nuocode/worktrees/wt1", "main"))
    acc.list = MagicMock(return_value=[
        WorktreeSummary(name="wt1", path="/repo/.nuocode/worktrees/wt1",
                        branch="main", active=True, manual=True),
    ])
    acc.enter = AsyncMock(return_value=None)
    acc.exit = AsyncMock(return_value=True)
    acc.remove = AsyncMock(return_value=None)
    return acc


# ── 测试用例 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_args_shows_usage() -> None:
    ui = _make_ui()
    await handle_worktree(ui, "")
    assert ui.println.called
    msg = ui.println.call_args[0][0]
    assert "用法" in msg or "/worktree" in msg


@pytest.mark.asyncio
async def test_create_success() -> None:
    acc = _make_accessor()
    ui = _make_ui(acc)
    await handle_worktree(ui, "create my-wt")
    acc.create.assert_awaited_once_with("my-wt")
    ui.println.assert_called_once()
    assert "my-wt" in ui.println.call_args[0][0] or "Worktree" in ui.println.call_args[0][0]


@pytest.mark.asyncio
async def test_create_missing_slug_shows_error() -> None:
    acc = _make_accessor()
    ui = _make_ui(acc)
    await handle_worktree(ui, "create")
    ui.error.assert_called_once()
    assert "slug" in ui.error.call_args[0][0].lower() or "缺少" in ui.error.call_args[0][0]


@pytest.mark.asyncio
async def test_create_no_accessor() -> None:
    ui = _make_ui(None)
    await handle_worktree(ui, "create wt1")
    ui.error.assert_called_once()
    assert "未启用" in ui.error.call_args[0][0] or "manager" in ui.error.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_list_shows_worktrees() -> None:
    acc = _make_accessor()
    ui = _make_ui(acc)
    await handle_worktree(ui, "list")
    acc.list.assert_called_once()
    ui.println.assert_called_once()
    msg = ui.println.call_args[0][0]
    assert "wt1" in msg


@pytest.mark.asyncio
async def test_list_empty() -> None:
    acc = _make_accessor()
    acc.list = MagicMock(return_value=[])
    ui = _make_ui(acc)
    await handle_worktree(ui, "list")
    msg = ui.println.call_args[0][0]
    assert "无" in msg or "empty" in msg.lower()


@pytest.mark.asyncio
async def test_enter_success() -> None:
    acc = _make_accessor()
    ui = _make_ui(acc)
    await handle_worktree(ui, "enter wt1")
    acc.enter.assert_awaited_once_with("wt1")
    ui.println.assert_called_once()


@pytest.mark.asyncio
async def test_exit_remove() -> None:
    acc = _make_accessor()
    ui = _make_ui(acc)
    await handle_worktree(ui, "exit --remove")
    acc.exit.assert_awaited_once_with("remove", False)
    ui.println.assert_called_once()


@pytest.mark.asyncio
async def test_remove_success() -> None:
    acc = _make_accessor()
    ui = _make_ui(acc)
    await handle_worktree(ui, "remove wt1")
    acc.remove.assert_awaited_once_with("wt1", False)
    ui.println.assert_called_once()


@pytest.mark.asyncio
async def test_unknown_subcommand_shows_error() -> None:
    ui = _make_ui(_make_accessor())
    await handle_worktree(ui, "foobar")
    ui.error.assert_called_once()
    assert "未知" in ui.error.call_args[0][0]
