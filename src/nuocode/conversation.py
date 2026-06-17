"""单会话多轮历史。"""

from __future__ import annotations

import threading

from nuocode.llm import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    Message,
    ToolCall,
    ToolResult,
)


class Conversation:
    def __init__(self) -> None:
        self._messages: list[Message] = []
        # 写写互斥 + 替换原子化；读端依旧返回副本，外部可无锁读
        self._lock = threading.RLock()

    def add_user(self, text: str) -> None:
        with self._lock:
            self._messages.append(Message(role=ROLE_USER, content=text))

    def add_assistant(self, text: str) -> None:
        with self._lock:
            self._messages.append(Message(role=ROLE_ASSISTANT, content=text))

    def add_assistant_with_tool_calls(self, text: str, calls: list[ToolCall]) -> None:
        """assistant 工具调用回合：preamble 文本 + 一组 tool_calls。"""
        with self._lock:
            self._messages.append(
                Message(role=ROLE_ASSISTANT, content=text, tool_calls=list(calls))
            )

    def add_tool_results(self, results: list[ToolResult]) -> None:
        """ROLE_TOOL 结果回合。"""
        with self._lock:
            self._messages.append(Message(role=ROLE_TOOL, tool_results=list(results)))

    def messages(self) -> list[Message]:
        """返回历史消息的浅拷贝列表（list 拷贝；元素仍是同一份 Message 引用）。"""
        with self._lock:
            return list(self._messages)

    def replace_messages(self, new_messages: list[Message]) -> None:
        """整体替换消息列表（compact 唯一写回入口）。

        语义：take ``self._lock`` → 用入参的浅拷贝替换底层列表。
        调用方有责任保证 ``new_messages`` 的不变量（不出现 user/user 等）。
        """
        with self._lock:
            self._messages = list(new_messages)

    def length(self) -> int:
        with self._lock:
            return len(self._messages)

    def last_role(self) -> str:
        """返回最后一条消息的 role；空历史返回 ""。"""
        with self._lock:
            return self._messages[-1].role if self._messages else ""

    def __len__(self) -> int:
        return self.length()
