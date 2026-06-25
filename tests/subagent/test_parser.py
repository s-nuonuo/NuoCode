"""subagent parser 单测（chap13 T3）。"""

from __future__ import annotations

import sys

import pytest

from nuocode.permission import Mode
from nuocode.subagent.definition import Source
from nuocode.subagent.parser import AGENT_NAME_REGEX, parse_definition, parse_file

# ─── 辅助 ───────────────────────────────────────────────────────────────


def _md(
    name: str = "test-agent",
    description: str = "a test agent",
    extra: str = "",
    body: str = "System prompt body.",
) -> bytes:
    fm_lines = [f"name: {name}", f"description: {description}"]
    if extra:
        fm_lines.append(extra)
    fm = "\n".join(fm_lines)
    return f"---\n{fm}\n---\n\n{body}".encode()


# ─── T3 参数化测试 ────────────────────────────────────────────────────────


class TestDefinitionFields:
    """AC1 覆盖：所有字段存在且默认值正确。"""

    def test_full_frontmatter(self):
        data = b"""---
name: my-agent
description: A full agent
tools:
  - read_file
  - grep
disallowedTools:
  - write_file
model: haiku
maxTurns: 10
permissionMode: acceptEdits
background: true
---

System prompt here.
"""
        d = parse_definition(data, "test.md", Source.USER)
        assert d.name == "my-agent"
        assert d.description == "A full agent"
        assert d.tools == ["read_file", "grep"]
        assert d.disallowed_tools == ["write_file"]
        assert d.model == "haiku"
        assert d.max_turns == 10
        assert d.permission_mode == Mode.ACCEPT_EDITS
        assert d.dont_ask is False
        assert d.background is True
        assert "System prompt here." in d.system_prompt
        assert d.file_path == "test.md"
        assert d.source == Source.USER

    def test_minimal_frontmatter(self):
        """仅必填字段，其余全部默认值。"""
        d = parse_definition(_md(), "test.md", Source.BUILTIN)
        assert d.name == "test-agent"
        assert d.tools == []
        assert d.disallowed_tools == []
        assert d.model == "inherit"
        assert d.max_turns == 0
        assert d.permission_mode == Mode.DEFAULT
        assert d.dont_ask is False
        assert d.background is False
        assert d.source == Source.BUILTIN


@pytest.mark.parametrize("model_val,expected", [
    ("haiku", "haiku"),
    ("sonnet", "sonnet"),
    ("opus", "opus"),
    ("inherit", "inherit"),
    ("", "inherit"),
])
def test_valid_models(model_val, expected):
    extra = f"model: {model_val}" if model_val else ""
    d = parse_definition(_md(extra=extra), "test.md", Source.BUILTIN)
    assert d.model == expected


def test_invalid_model_fallback(capsys):
    """非法 model → stderr 警告 + fallback to inherit。"""
    d = parse_definition(_md(extra="model: gpt-4"), "test.md", Source.USER)
    assert d.model == "inherit"
    captured = capsys.readouterr()
    assert "unknown model" in captured.err
    assert "inherit" in captured.err


def test_permission_mode_dont_ask():
    """permissionMode: dontAsk → dont_ask=True, permission_mode=DEFAULT。"""
    d = parse_definition(_md(extra="permissionMode: dontAsk"), "test.md", Source.PROJECT)
    assert d.dont_ask is True
    assert d.permission_mode == Mode.DEFAULT


def test_permission_mode_plan():
    d = parse_definition(_md(extra="permissionMode: plan"), "test.md", Source.BUILTIN)
    assert d.permission_mode == Mode.PLAN
    assert d.dont_ask is False


def test_invalid_permission_mode_fallback(capsys):
    d = parse_definition(_md(extra="permissionMode: weirdMode"), "test.md", Source.USER)
    assert d.permission_mode == Mode.DEFAULT
    captured = capsys.readouterr()
    assert "unknown permissionMode" in captured.err


def test_missing_name_raises():
    data = b"---\ndescription: something\n---\nbody"
    with pytest.raises(ValueError, match="name"):
        parse_definition(data, "test.md", Source.BUILTIN)


def test_empty_name_raises():
    data = b"---\nname: \ndescription: something\n---\nbody"
    with pytest.raises(ValueError):
        parse_definition(data, "test.md", Source.BUILTIN)


def test_missing_description_raises():
    data = b"---\nname: my-agent\n---\nbody"
    with pytest.raises(ValueError, match="description"):
        parse_definition(data, "test.md", Source.BUILTIN)


def test_unclosed_frontmatter_raises():
    data = b"---\nname: my-agent\ndescription: x\nbody without close"
    with pytest.raises(ValueError, match="frontmatter"):
        parse_definition(data, "test.md", Source.BUILTIN)


def test_no_frontmatter_raises():
    data = b"Just plain text without frontmatter."
    with pytest.raises(ValueError):
        parse_definition(data, "test.md", Source.BUILTIN)


def test_body_extraction():
    data = b"---\nname: a\ndescription: b\n---\n\nHello world\nLine 2\n"
    d = parse_definition(data, "test.md", Source.BUILTIN)
    assert "Hello world" in d.system_prompt
    assert "Line 2" in d.system_prompt


def test_parse_file(tmp_path):
    md_file = tmp_path / "test-agent.md"
    md_file.write_bytes(_md(name="file-agent", description="from file"))
    d = parse_file(str(md_file), Source.PROJECT)
    assert d.name == "file-agent"
    assert d.description == "from file"


def test_name_regex_allows_uppercase():
    d = parse_definition(_md(name="Explore"), "test.md", Source.BUILTIN)
    assert d.name == "Explore"


def test_name_regex_rejects_invalid():
    data = b"---\nname: 123bad\ndescription: x\n---\nbody"
    with pytest.raises(ValueError):
        parse_definition(data, "test.md", Source.BUILTIN)
