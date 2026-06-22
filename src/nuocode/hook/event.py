"""hook.event: 11 个生命周期事件枚举与辅助函数（chap12）。"""

from __future__ import annotations

import enum


class Event(str, enum.Enum):
    """11 个 nuocode 生命周期事件。值与 YAML 配置字面量一致。"""

    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    SESSION_RESUME = "SessionResume"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    STOP = "Stop"
    PRE_USER_MESSAGE = "PreUserMessage"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"
    NOTIFICATION = "Notification"


BLOCKING_EVENTS: frozenset[Event] = frozenset({Event.PRE_TOOL_USE, Event.USER_PROMPT_SUBMIT})
"""拦截类事件集合：仅这两个事件支持 Hook 通过 exit code 2 / HTTP decision=block 表达拦截信号。"""


def is_blocking(e: Event) -> bool:
    """判断事件是否为拦截类（支持 shell exit 2 / http block 拦截）。"""
    return e in BLOCKING_EVENTS


def parse_event(s: str) -> Event | None:
    """用字面量字符串反查 Event 枚举；未知值返回 None。"""
    try:
        return Event(s)
    except ValueError:
        return None


__all__ = ["Event", "BLOCKING_EVENTS", "is_blocking", "parse_event"]
