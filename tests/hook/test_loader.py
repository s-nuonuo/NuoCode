"""hook.loader 单元测试（chap12 T9）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from nuocode.hook.loader import load


def _write_hooks(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ────────── 合法 YAML ──────────

def test_load_valid_two_rules(tmp_path: Path) -> None:
    hooks_file = tmp_path / ".nuocode" / "hooks.yaml"
    _write_hooks(
        hooks_file,
        """
hooks:
  - name: on-start
    event: SessionStart
    action:
      type: prompt
      text: "Hello!"
  - name: pre-write
    event: PreToolUse
    if:
      all_of:
        - field: tool_name
          match: {type: exact, value: write_file}
    action:
      type: shell
      command: "echo hi"
""",
    )
    engine = load(tmp_path)
    assert len(engine.rules) == 2
    assert engine.rules[0].name == "on-start"
    assert engine.rules[1].name == "pre-write"
    assert tmp_path / ".nuocode" / "hooks.yaml" in [Path(s) for s in engine.sources] or \
        str(hooks_file) in engine.sources


# ────────── 字段缺失 ──────────

def test_load_missing_name_skips(tmp_path: Path, capsys) -> None:
    _write_hooks(
        tmp_path / ".nuocode" / "hooks.yaml",
        """
hooks:
  - event: SessionStart
    action:
      type: prompt
      text: "hi"
""",
    )
    engine = load(tmp_path)
    assert len(engine.rules) == 0
    captured = capsys.readouterr()
    assert "name" in captured.err


def test_load_unknown_event_skips(tmp_path: Path, capsys) -> None:
    _write_hooks(
        tmp_path / ".nuocode" / "hooks.yaml",
        """
hooks:
  - name: bad
    event: UnknownEvent
    action:
      type: prompt
      text: "x"
""",
    )
    engine = load(tmp_path)
    assert len(engine.rules) == 0
    captured = capsys.readouterr()
    assert "unknown event" in captured.err and "UnknownEvent" in captured.err


def test_load_invalid_action_type_skips(tmp_path: Path, capsys) -> None:
    _write_hooks(
        tmp_path / ".nuocode" / "hooks.yaml",
        """
hooks:
  - name: bad
    event: SessionStart
    action:
      type: magic
""",
    )
    engine = load(tmp_path)
    assert len(engine.rules) == 0
    captured = capsys.readouterr()
    assert "unknown action type" in captured.err


# ────────── all_of + any_of 互斥 ──────────

def test_load_both_allof_anyof_skips(tmp_path: Path, capsys) -> None:
    _write_hooks(
        tmp_path / ".nuocode" / "hooks.yaml",
        """
hooks:
  - name: bad-cond
    event: SessionStart
    if:
      all_of:
        - field: x
          match: {type: exact, value: "y"}
      any_of:
        - field: x
          match: {type: exact, value: "y"}
    action:
      type: prompt
      text: "x"
""",
    )
    engine = load(tmp_path)
    assert len(engine.rules) == 0
    captured = capsys.readouterr()
    assert "all_of and any_of" in captured.err or "cannot have both" in captured.err


# ────────── async + 拦截事件冲突 ──────────

def test_load_async_blocking_event_skips(tmp_path: Path, capsys) -> None:
    _write_hooks(
        tmp_path / ".nuocode" / "hooks.yaml",
        """
hooks:
  - name: bad-async
    event: PreToolUse
    async: true
    action:
      type: shell
      command: "echo x"
""",
    )
    engine = load(tmp_path)
    assert len(engine.rules) == 0
    captured = capsys.readouterr()
    assert "async not allowed for blocking events" in captured.err


# ────────── matcher 编译失败 ──────────

def test_load_invalid_regex_skips(tmp_path: Path, capsys) -> None:
    _write_hooks(
        tmp_path / ".nuocode" / "hooks.yaml",
        """
hooks:
  - name: bad-regex
    event: SessionStart
    if:
      all_of:
        - field: x
          match: {type: regex, value: "[invalid"}
    action:
      type: prompt
      text: "x"
""",
    )
    engine = load(tmp_path)
    assert len(engine.rules) == 0
    captured = capsys.readouterr()
    assert "matcher compile failed" in captured.err or "invalid" in captured.err.lower()


# ────────── 双层同名冲突 ──────────

def test_load_duplicate_name_skips_later(tmp_path: Path, monkeypatch, capsys) -> None:
    """project 级的 hook 优先，user 级同名被跳过。"""
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    # 确保 Path.home() 也返回 fake_home
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    proj_hooks = tmp_path / ".nuocode" / "hooks.yaml"
    _write_hooks(
        proj_hooks,
        """
hooks:
  - name: shared
    event: SessionStart
    action:
      type: prompt
      text: "from project"
""",
    )
    user_hooks = fake_home / ".nuocode" / "hooks.yaml"
    _write_hooks(
        user_hooks,
        """
hooks:
  - name: shared
    event: SessionStart
    action:
      type: prompt
      text: "from user"
""",
    )
    engine = load(tmp_path)
    assert len(engine.rules) == 1
    assert engine.rules[0].action.prompt.text == "from project"
    captured = capsys.readouterr()
    assert "duplicate" in captured.err


# ────────── 文件不存在不报错 ──────────

def test_load_no_file_returns_empty(tmp_path: Path) -> None:
    engine = load(tmp_path)
    assert len(engine.rules) == 0
    assert engine.sources == []


# ────────── YAML 解析失败 ──────────

def test_load_invalid_yaml_skips_file(tmp_path: Path, capsys) -> None:
    _write_hooks(
        tmp_path / ".nuocode" / "hooks.yaml",
        "hooks: [\n  - {bad yaml]",
    )
    engine = load(tmp_path)
    assert len(engine.rules) == 0
    captured = capsys.readouterr()
    assert "YAML parse error" in captured.err or "error" in captured.err.lower()


# ────────── timeout 解析 ──────────

def test_load_custom_timeout(tmp_path: Path) -> None:
    _write_hooks(
        tmp_path / ".nuocode" / "hooks.yaml",
        """
hooks:
  - name: slow
    event: SessionStart
    timeout: 5s
    action:
      type: prompt
      text: "x"
""",
    )
    engine = load(tmp_path)
    assert len(engine.rules) == 1
    assert engine.rules[0].timeout_s == 5.0
