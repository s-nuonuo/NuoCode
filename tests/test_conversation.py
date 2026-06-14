from __future__ import annotations

from nuocode.conversation import Conversation
from nuocode.llm import ROLE_ASSISTANT, ROLE_TOOL, ROLE_USER, ToolCall, ToolResult


def test_empty() -> None:
    c = Conversation()
    assert c.messages() == []
    assert len(c) == 0


def test_order_and_roles() -> None:
    c = Conversation()
    c.add_user("hi")
    c.add_assistant("hello")
    c.add_user("how are you")
    msgs = c.messages()
    assert [m.role for m in msgs] == [ROLE_USER, ROLE_ASSISTANT, ROLE_USER]
    assert [m.content for m in msgs] == ["hi", "hello", "how are you"]


def test_messages_returns_copy() -> None:
    c = Conversation()
    c.add_user("hi")
    snapshot = c.messages()
    snapshot.clear()
    assert len(c.messages()) == 1


def test_tool_call_and_result_roundtrip() -> None:
    c = Conversation()
    c.add_user("read pyproject.toml")
    calls = [ToolCall(id="t1", name="read_file", input='{"path":"pyproject.toml"}')]
    c.add_assistant_with_tool_calls("我先看一下文件。", calls)
    c.add_tool_results([ToolResult(tool_call_id="t1", content="contents...", is_error=False)])
    c.add_assistant("文件内容如下: …")

    msgs = c.messages()
    assert len(msgs) == 4
    assert [m.role for m in msgs] == [
        ROLE_USER,
        ROLE_ASSISTANT,
        ROLE_TOOL,
        ROLE_ASSISTANT,
    ]
    assert msgs[1].tool_calls[0].name == "read_file"
    assert msgs[1].content == "我先看一下文件。"
    assert msgs[2].tool_results[0].tool_call_id == "t1"
    assert msgs[2].tool_results[0].is_error is False
    assert msgs[3].content.startswith("文件")


def test_last_role() -> None:
    c = Conversation()
    assert c.last_role() == ""
    c.add_user("hi")
    assert c.last_role() == ROLE_USER
    c.add_assistant_with_tool_calls("", [ToolCall(id="t1", name="x", input="{}")])
    assert c.last_role() == ROLE_ASSISTANT
    c.add_tool_results([ToolResult(tool_call_id="t1", content="ok")])
    assert c.last_role() == ROLE_TOOL
    c.add_assistant("done")
    assert c.last_role() == ROLE_ASSISTANT
