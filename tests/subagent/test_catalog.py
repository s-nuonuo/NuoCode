"""subagent catalog 单测（chap13 T7）。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nuocode.subagent.catalog import Catalog, load_catalog
from nuocode.subagent.definition import Source
from nuocode.subagent.embed import builtin_definitions


# ─── 内置 ──────────────────────────────────────────────────────────────────


class TestBuiltin:
    def test_builtin_count(self):
        defs = builtin_definitions()
        assert len(defs) == 3

    def test_builtin_names(self):
        defs = builtin_definitions()
        names = {d.name.lower() for d in defs}
        assert "general-purpose" in names
        assert "explore" in names
        assert "plan" in names

    def test_builtin_source(self):
        for d in builtin_definitions():
            assert d.source == Source.BUILTIN

    def test_builtin_descriptions_nonempty(self):
        for d in builtin_definitions():
            assert d.description.strip()


# ─── fork_definition ───────────────────────────────────────────────────────


def test_fork_definition_is_fork():
    c = Catalog()
    fd = c.fork_definition()
    assert fd.is_fork() is True
    assert fd.name == "__fork__"


# ─── 三层覆盖 ──────────────────────────────────────────────────────────────


def _write_explore(dir_path: Path, description: str = "project explore") -> None:
    """在目录下写一个 Explore 定义文件。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: Explore\ndescription: {description}\nmaxTurns: 5\n---\nbody\n"
    (dir_path / "explore.md").write_text(content)


class TestCatalogOverride:
    def test_builtin_only(self, tmp_path):
        """只有内置时，resolve 返回 builtin source。"""
        c = load_catalog(str(tmp_path))
        d = c.resolve("explore")
        assert d is not None
        assert d.source == Source.BUILTIN

    def test_project_overrides_builtin(self, tmp_path, monkeypatch):
        """项目级同名覆盖内置。"""
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        project_agents = tmp_path / ".nuocode" / "agents"
        _write_explore(project_agents, "project level explore")

        c = load_catalog(str(tmp_path))
        d = c.resolve("Explore")
        assert d is not None
        assert d.source == Source.PROJECT
        assert "project level" in d.description

    def test_user_overrides_builtin(self, tmp_path, monkeypatch):
        """用户级同名覆盖内置，但不覆盖项目级。"""
        fake_home = tmp_path / "fakehome"
        monkeypatch.setenv("HOME", str(fake_home))
        user_agents = fake_home / ".nuocode" / "agents"
        _write_explore(user_agents, "user level explore")

        c = load_catalog(str(tmp_path))
        d = c.resolve("explore")
        assert d is not None
        assert d.source == Source.USER

    def test_project_beats_user(self, tmp_path, monkeypatch):
        """项目级优先于用户级。"""
        fake_home = tmp_path / "fakehome"
        monkeypatch.setenv("HOME", str(fake_home))
        user_agents = fake_home / ".nuocode" / "agents"
        _write_explore(user_agents, "user level")
        project_agents = tmp_path / ".nuocode" / "agents"
        _write_explore(project_agents, "project level")

        c = load_catalog(str(tmp_path))
        d = c.resolve("explore")
        assert d is not None
        assert d.source == Source.PROJECT


# ─── 错误处理 ──────────────────────────────────────────────────────────────


def test_bad_file_skipped(tmp_path, capsys, monkeypatch):
    """非法 frontmatter 文件被跳过，其他文件仍正常加载。"""
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    project_agents = tmp_path / ".nuocode" / "agents"
    project_agents.mkdir(parents=True)

    # 非法文件
    (project_agents / "bad.md").write_text("no frontmatter at all")
    # 合法文件
    (project_agents / "good.md").write_text(
        "---\nname: good-agent\ndescription: good\n---\nbody\n"
    )

    c = load_catalog(str(tmp_path))
    captured = capsys.readouterr()
    assert "解析失败" in captured.err or "bad.md" in captured.err
    d = c.resolve("good-agent")
    assert d is not None
    assert d.name == "good-agent"


# ─── resolve / list ────────────────────────────────────────────────────────


def test_resolve_case_insensitive():
    c = Catalog()
    from nuocode.subagent.embed import builtin_definitions

    for d in builtin_definitions():
        c._add_all([d])
    assert c.resolve("explore") is not None
    assert c.resolve("EXPLORE") is not None
    assert c.resolve("Explore") is not None


def test_list_sorted():
    c = Catalog()
    for d in builtin_definitions():
        c._add_all([d])
    names = [d.name.lower() for d in c.list()]
    assert names == sorted(names)
