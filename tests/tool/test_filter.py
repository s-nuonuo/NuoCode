"""工具过滤多层防线测试（chap13 T9）。"""

from __future__ import annotations

import pytest

from nuocode.tool.filter import (
    ALL_AGENT_DISALLOWED_TOOLS,
    ASYNC_AGENT_ALLOWED_TOOLS,
    CUSTOM_AGENT_DISALLOWED_TOOLS,
    FilterParams,
    apply_agent_tool_filter,
    is_mcp_or_skill,
)

# ─── 常量存在性 ────────────────────────────────────────────────────────────


class TestConstants:
    def test_all_agent_disallowed_exists(self):
        assert isinstance(ALL_AGENT_DISALLOWED_TOOLS, list)
        assert "Agent" in ALL_AGENT_DISALLOWED_TOOLS

    def test_custom_agent_disallowed_exists(self):
        assert isinstance(CUSTOM_AGENT_DISALLOWED_TOOLS, list)

    def test_async_agent_allowed_exists(self):
        assert isinstance(ASYNC_AGENT_ALLOWED_TOOLS, list)
        for t in ["read_file", "bash", "grep", "glob"]:
            assert t in ASYNC_AGENT_ALLOWED_TOOLS, f"{t} should be in ASYNC_AGENT_ALLOWED_TOOLS"


# ─── is_mcp_or_skill ──────────────────────────────────────────────────────


@pytest.mark.parametrize("name,expected", [
    ("mcp__myserver__tool", True),
    ("mcp__x", True),
    ("mcp_not_double", False),
    ("Agent", False),
    ("read_file", False),
    ("", False),
])
def test_is_mcp_or_skill(name, expected):
    assert is_mcp_or_skill(name) == expected


# ─── apply_agent_tool_filter ──────────────────────────────────────────────


_ALL_TOOLS = ["Agent", "read_file", "write_file", "edit_file", "bash", "grep", "glob",
              "TaskList", "TaskGet", "TaskStop", "SendMessage", "some_tool", "mcp__srv__t"]


def _params(**kwargs) -> FilterParams:
    defaults = dict(all=_ALL_TOOLS, source=0, background=False)
    defaults.update(kwargs)
    return FilterParams(**defaults)


class TestApplyFilter:
    def test_default_removes_agent(self):
        result = apply_agent_tool_filter(_params())
        assert "Agent" not in result
        assert "read_file" in result

    def test_background_intersects_async_whitelist(self):
        result = apply_agent_tool_filter(_params(background=True))
        # Agent 已被全局禁止，不在后台结果中
        assert "Agent" not in result
        # 基础工具保留
        assert "read_file" in result
        assert "bash" in result
        # TaskList 等元工具被后台白名单过滤掉
        assert "TaskList" not in result
        assert "TaskGet" not in result
        assert "some_tool" not in result

    def test_background_keeps_mcp_tools(self):
        result = apply_agent_tool_filter(_params(background=True))
        assert "mcp__srv__t" in result

    def test_disallowed_removes_tools(self):
        result = apply_agent_tool_filter(_params(disallowed=["bash"]))
        assert "bash" not in result
        assert "read_file" in result

    def test_allowed_whitelist_narrows(self):
        result = apply_agent_tool_filter(_params(allowed=["read_file", "grep"]))
        assert set(result) == {"read_file", "grep"}

    def test_disallowed_and_allowed_combined(self):
        """allowed 先收窄，disallowed 再排除。"""
        result = apply_agent_tool_filter(
            _params(allowed=["read_file", "bash", "grep"], disallowed=["bash"])
        )
        assert "bash" not in result
        assert "read_file" in result
        assert "grep" in result

    def test_background_and_mcp(self):
        result = apply_agent_tool_filter(_params(background=True))
        assert "mcp__srv__t" in result

    def test_empty_allowed_does_not_narrow(self):
        """allowed=[] 不收窄（全量减去黑名单）。"""
        result = apply_agent_tool_filter(_params(allowed=[]))
        assert "read_file" in result
        assert "bash" in result

    def test_agent_never_in_result(self):
        """无论什么参数，Agent 都不在结果中。"""
        result = apply_agent_tool_filter(
            _params(allowed=["Agent", "read_file"], disallowed=[])
        )
        assert "Agent" not in result
