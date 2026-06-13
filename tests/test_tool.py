"""tool 包单测：注册中心 + 各工具核心行为。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nuocode.tool import Registry, Result, new_default_registry
from nuocode.tool.bash import BashTool
from nuocode.tool.edit_file import EditFileTool
from nuocode.tool.glob_tool import GlobTool
from nuocode.tool.grep_tool import GrepTool
from nuocode.tool.read_file import ReadFileTool
from nuocode.tool.write_file import WriteFileTool

# ───────── Registry ─────────


def test_registry_definitions_count_and_order() -> None:
    reg = new_default_registry()
    defs = reg.definitions()
    names = [d.name for d in defs]
    assert names == [
        "read_file",
        "write_file",
        "edit_file",
        "bash",
        "glob",
        "grep",
    ]
    assert reg.get("read_file") is not None
    assert reg.get("nope") is None


def test_registry_register_duplicate() -> None:
    reg = Registry()
    reg.register(ReadFileTool())
    with pytest.raises(ValueError):
        reg.register(ReadFileTool())


async def test_registry_unknown_tool_returns_error() -> None:
    reg = new_default_registry()
    r = await reg.execute("nope", "{}")
    assert r.is_error
    assert "未知工具" in r.content


async def test_registry_timeout_short() -> None:
    reg = new_default_registry()
    r = await reg.execute("bash", json.dumps({"command": "sleep 5"}), timeout=0.2)
    assert r.is_error
    assert "超时" in r.content


# ───────── read_file ─────────


async def test_read_file_with_line_numbers(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hello\nworld\n")
    r = await ReadFileTool().execute(json.dumps({"path": str(f)}))
    assert not r.is_error
    assert "1\thello" in r.content
    assert "2\tworld" in r.content


async def test_read_file_missing() -> None:
    r = await ReadFileTool().execute(json.dumps({"path": "/no/such/file"}))
    assert r.is_error
    assert "不存在" in r.content


async def test_read_file_dir(tmp_path: Path) -> None:
    r = await ReadFileTool().execute(json.dumps({"path": str(tmp_path)}))
    assert r.is_error
    assert "目录" in r.content


# ───────── write_file ─────────


async def test_write_file_creates_parents(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c.txt"
    r = await WriteFileTool().execute(json.dumps({"path": str(target), "content": "hi"}))
    assert not r.is_error
    assert target.read_text() == "hi"


async def test_write_file_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "x.txt"
    target.write_text("old")
    r = await WriteFileTool().execute(json.dumps({"path": str(target), "content": "new"}))
    assert not r.is_error
    assert target.read_text() == "new"


# ───────── edit_file ─────────


async def test_edit_file_unique(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("alpha\nbeta\ngamma\n")
    r = await EditFileTool().execute(
        json.dumps({"path": str(f), "old_string": "beta", "new_string": "BETA"})
    )
    assert not r.is_error
    assert f.read_text() == "alpha\nBETA\ngamma\n"


async def test_edit_file_zero(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("a\nb\n")
    r = await EditFileTool().execute(
        json.dumps({"path": str(f), "old_string": "ZZZ", "new_string": "X"})
    )
    assert r.is_error
    assert "未找到匹配" in r.content


async def test_edit_file_multiple(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("foo foo foo\n")
    r = await EditFileTool().execute(
        json.dumps({"path": str(f), "old_string": "foo", "new_string": "bar"})
    )
    assert r.is_error
    assert "匹配到 3 处" in r.content


# ───────── bash ─────────


async def test_bash_echo() -> None:
    r = await BashTool().execute(json.dumps({"command": "echo hi"}))
    assert not r.is_error
    assert "hi" in r.content
    assert "exit_code: 0" in r.content


async def test_bash_nonzero() -> None:
    r = await BashTool().execute(json.dumps({"command": "false"}))
    # 非零退出按结果回灌（不视为 error）
    assert not r.is_error
    assert "exit_code: 1" in r.content


# ───────── glob ─────────


async def test_glob_python_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    r = await GlobTool().execute(json.dumps({"pattern": "**/*.py", "path": str(tmp_path)}))
    assert not r.is_error
    lines = r.content.splitlines()
    assert any(line.endswith("a.py") for line in lines)
    assert any(line.endswith("b.py") for line in lines)
    assert not any("c.txt" in line for line in lines)


# ───────── grep ─────────


async def test_grep_finds_keyword(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def hello():\n    return 1\n")
    (tmp_path / "b.txt").write_text("nothing here\n")
    r = await GrepTool().execute(json.dumps({"pattern": "hello", "path": str(tmp_path)}))
    assert not r.is_error
    assert "a.py" in r.content
    assert ":1:" in r.content


async def test_grep_invalid_regex(tmp_path: Path) -> None:
    r = await GrepTool().execute(json.dumps({"pattern": "[unclosed", "path": str(tmp_path)}))
    assert r.is_error
    assert "正则非法" in r.content


# ───────── 共用：参数校验 ─────────


async def test_read_file_bad_args() -> None:
    r = await ReadFileTool().execute("not json")
    assert r.is_error
    assert "JSON 解析失败" in r.content


def test_result_dataclass() -> None:
    assert Result(content="x").is_error is False
