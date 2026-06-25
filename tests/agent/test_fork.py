"""fork 辅助函数测试（chap13 T13）。"""

from __future__ import annotations

from nuocode.agent.fork import (
    FORK_BOILERPLATE,
    FORK_BOILERPLATE_TAG,
    build_forked_messages,
    is_fork_context,
)
from nuocode.llm import Message, ToolCall, ToolResult


# ─── build_forked_messages ────────────────────────────────────────────────


def test_empty_parent_produces_single_user():
    result = build_forked_messages([], "do something")
    assert len(result) == 1
    assert result[0].role == "user"
    assert FORK_BOILERPLATE_TAG in result[0].content
    assert "do something" in result[0].content


def test_boilerplate_prepended_to_task():
    result = build_forked_messages([], "my task")
    content = result[-1].content
    assert content.startswith(FORK_BOILERPLATE_TAG) or FORK_BOILERPLATE in content
    assert "my task" in content


def test_parent_with_complete_exchange_cloned():
    parent = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi",
                tool_calls=[ToolCall(id="tc1", name="bash", input='{"cmd":"ls"}')]),
        Message(role="tool", tool_results=[ToolResult(tool_call_id="tc1", content="file.py")]),
    ]
    result = build_forked_messages(parent, "next task")
    # 克隆了原始 3 条 + 追加 1 条 user
    assert len(result) == 4
    assert result[-1].role == "user"
    assert "next task" in result[-1].content


def test_dangling_tool_use_gets_placeholder():
    """末尾 assistant 有 tool_use 但无 tool_result，应追加 placeholder。"""
    parent = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="",
                tool_calls=[
                    ToolCall(id="tc1", name="bash", input='{}'),
                    ToolCall(id="tc2", name="read_file", input='{}'),
                ]),
        # 只有 tc1 配了 result，tc2 没有
        Message(role="tool", tool_results=[ToolResult(tool_call_id="tc1", content="ok")]),
    ]
    result = build_forked_messages(parent, "task")
    # 消息应该是：user + assistant + tool + placeholder_tool + user_boilerplate
    assert result[-1].role == "user"
    # 找到 placeholder
    placeholder_msgs = [m for m in result if m.role == "tool" and
                        any("skipped" in (tr.content or "") for tr in m.tool_results)]
    assert len(placeholder_msgs) >= 1
    placeholder_ids = {tr.tool_call_id for m in placeholder_msgs for tr in m.tool_results}
    assert "tc2" in placeholder_ids


def test_deep_copy_independence():
    """深拷贝后修改 result 不影响 parent。"""
    parent = [Message(role="user", content="original")]
    result = build_forked_messages(parent, "task")
    result[0].content = "modified"
    assert parent[0].content == "original"


# ─── is_fork_context ─────────────────────────────────────────────────────────


def test_is_fork_context_detects_boilerplate():
    msgs = [Message(role="user", content=f"{FORK_BOILERPLATE}do it")]
    assert is_fork_context(msgs) is True


def test_is_fork_context_false_without_boilerplate():
    msgs = [
        Message(role="user", content="normal message"),
        Message(role="assistant", content="normal reply"),
    ]
    assert is_fork_context(msgs) is False


def test_is_fork_context_empty():
    assert is_fork_context([]) is False


def test_build_result_is_fork_context():
    """build_forked_messages 产出的消息列表应被 is_fork_context 识别。"""
    result = build_forked_messages([], "some task")
    assert is_fork_context(result) is True
