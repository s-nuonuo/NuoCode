"""单会话多轮历史。"""

from __future__ import annotations

import threading
from collections.abc import Callable

from nuocode.llm import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    Message,
    ToolCall,
    ToolResult,
)


class Conversation:
    def __init__(
        self,
        on_append: Callable[[Message], None] | None = None,
        on_replace: Callable[[list[Message]], None] | None = None,
    ) -> None:
        self._messages: list[Message] = []
        # 写写互斥 + 替换原子化；读端依旧返回副本，外部可无锁读
        self._lock = threading.RLock()
        self._on_append = on_append
        self._on_replace = on_replace

    @classmethod
    def from_messages(
        cls,
        msgs: list[Message],
        on_append: Callable[[Message], None] | None = None,
        on_replace: Callable[[list[Message]], None] | None = None,
    ) -> Conversation:
        """从已有消息列表创建会话（恢复场景）。

        初始消息不会触发 on_append 回调（视为已存在历史）。
        """
        c = cls(on_append=on_append, on_replace=on_replace)
        c._messages = list(msgs)
        return c

    def add_user(self, text: str) -> None:
        msg = Message(role=ROLE_USER, content=text)
        with self._lock:
            self._messages.append(msg)
        if self._on_append is not None:
            self._on_append(msg)

    def add_assistant(self, text: str) -> None:
        msg = Message(role=ROLE_ASSISTANT, content=text)
        with self._lock:
            self._messages.append(msg)
        if self._on_append is not None:
            self._on_append(msg)

    def add_assistant_with_tool_calls(self, text: str, calls: list[ToolCall]) -> None:
        """assistant 工具调用回合：preamble 文本 + 一组 tool_calls。"""
        msg = Message(role=ROLE_ASSISTANT, content=text, tool_calls=list(calls))
        with self._lock:
            self._messages.append(msg)
        if self._on_append is not None:
            self._on_append(msg)

    def add_tool_results(self, results: list[ToolResult]) -> None:
        """ROLE_TOOL 结果回合。"""
        msg = Message(role=ROLE_TOOL, tool_results=list(results))
        with self._lock:
            self._messages.append(msg)
        if self._on_append is not None:
            self._on_append(msg)

    def messages(self) -> list[Message]:
        """返回历史消息的浅拷贝列表（list 拷贝；元素仍是同一份 Message 引用）。"""
        with self._lock:
            return list(self._messages)

    def replace_messages(self, new_messages: list[Message]) -> None:
        """整体替换消息列表（compact 唯一写回入口）。"""
        with self._lock:
            self._messages = list(new_messages)
            snapshot = list(self._messages)
        if self._on_replace is not None:
            self._on_replace(snapshot)

    def length(self) -> int:
        with self._lock:
            return len(self._messages)

    def last_role(self) -> str:
        """返回最后一条消息的 role；空历史返回 ""。"""
        with self._lock:
            return self._messages[-1].role if self._messages else ""

    def __len__(self) -> int:
        return self.length()
