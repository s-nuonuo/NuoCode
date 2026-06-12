from __future__ import annotations

from nuocode.conversation import Conversation


def test_empty() -> None:
    c = Conversation()
    assert c.messages() == []


def test_order_and_roles() -> None:
    c = Conversation()
    c.add_user("hi")
    c.add_assistant("hello")
    c.add_user("how are you")
    msgs = c.messages()
    assert [m.role for m in msgs] == ["user", "assistant", "user"]
    assert [m.content for m in msgs] == ["hi", "hello", "how are you"]


def test_messages_returns_copy() -> None:
    c = Conversation()
    c.add_user("hi")
    snapshot = c.messages()
    snapshot.clear()
    assert len(c.messages()) == 1
