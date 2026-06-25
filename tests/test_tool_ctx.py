"""test_tool_ctx.py：with_cwd / cwd_from_ctx / resolve_path 单测（chap14 T8）。"""

import asyncio
from pathlib import Path

import pytest

from nuocode.tool.ctx import cwd_from_ctx, resolve_path, with_cwd


def test_resolve_path_absolute() -> None:
    """绝对路径直接返回。"""
    assert resolve_path("/tmp/test") == "/tmp/test"


def test_resolve_path_empty_no_ctx() -> None:
    """空字符串且无 ctx → 返回进程 cwd。"""
    result = resolve_path("")
    assert result == str(Path.cwd())


def test_resolve_path_relative_no_ctx() -> None:
    """相对路径且无 ctx → 拼接到进程 cwd。"""
    result = resolve_path("subdir/file.txt")
    assert result == str(Path.cwd() / "subdir" / "file.txt")


def test_with_cwd_sets_ctx(tmp_path: Path) -> None:
    """with_cwd 设置 ctx 后 cwd_from_ctx 能取到值。"""
    assert cwd_from_ctx() is None
    with with_cwd(str(tmp_path)):
        assert cwd_from_ctx() == str(tmp_path)
    assert cwd_from_ctx() is None  # 退出后恢复


def test_resolve_path_with_ctx(tmp_path: Path) -> None:
    """有 ctx cwd 时，相对路径以 ctx cwd 为基准。"""
    with with_cwd(str(tmp_path)):
        result = resolve_path("a.txt")
        assert result == str(tmp_path / "a.txt")


def test_resolve_path_empty_with_ctx(tmp_path: Path) -> None:
    """有 ctx cwd 时，空字符串返回 ctx cwd 本身。"""
    with with_cwd(str(tmp_path)):
        result = resolve_path("")
        assert result == str(tmp_path)


def test_with_cwd_empty_no_effect() -> None:
    """with_cwd('') 不改变 ctx。"""
    with with_cwd(""):
        assert cwd_from_ctx() is None


def test_with_cwd_nested(tmp_path: Path) -> None:
    """嵌套 with_cwd 正确恢复。"""
    inner = tmp_path / "inner"
    with with_cwd(str(tmp_path)):
        assert cwd_from_ctx() == str(tmp_path)
        with with_cwd(str(inner)):
            assert cwd_from_ctx() == str(inner)
        assert cwd_from_ctx() == str(tmp_path)
    assert cwd_from_ctx() is None


def test_with_cwd_absolute_path_unchanged(tmp_path: Path) -> None:
    """在 ctx cwd 下解析绝对路径不受 ctx 影响。"""
    with with_cwd(str(tmp_path)):
        result = resolve_path("/absolute/path")
        assert result == "/absolute/path"


@pytest.mark.asyncio
async def test_with_cwd_async_isolation(tmp_path: Path) -> None:
    """不同协程的 ctx cwd 互相隔离。"""
    results: dict[str, str | None] = {}

    async def task_a() -> None:
        with with_cwd(str(tmp_path / "a")):
            await asyncio.sleep(0.01)
            results["a"] = cwd_from_ctx()

    async def task_b() -> None:
        await asyncio.sleep(0.005)
        results["b"] = cwd_from_ctx()

    await asyncio.gather(task_a(), task_b())
    assert results["a"] == str(tmp_path / "a")
    assert results["b"] is None  # task_b 没有设置 ctx
