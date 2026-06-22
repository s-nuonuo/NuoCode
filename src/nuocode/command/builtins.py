"""一次性把 12 条内置命令注册进 Registry。"""

from __future__ import annotations

from nuocode.command.builtin_local import (
    handle_memory,
    handle_permission,
    handle_session,
    handle_status,
    make_help_handler,
)
from nuocode.command.builtin_prompt import REVIEW_DIRECTIVE, handle_do, handle_review
from nuocode.command.builtin_ui import (
    handle_clear,
    handle_compact,
    handle_exit,
    handle_plan,
    handle_resume,
)
from nuocode.command.command import Command, Kind
from nuocode.command.registry import Registry


def register_builtins(reg: Registry) -> None:
    """按字典序注册 12 条 Command。"""
    items: list[Command] = [
        Command(name="clear", description="清空当前会话并开启新 session", kind=Kind.UI, handler=handle_clear),
        Command(name="compact", description="手动触发上下文压缩", kind=Kind.UI, handler=handle_compact),
        Command(name="do", description="切回默认模式并执行已确认的计划", kind=Kind.PROMPT, handler=handle_do),
        Command(name="exit", description="退出 nuocode", kind=Kind.UI, handler=handle_exit),
        Command(name="help", description="显示所有可用命令", kind=Kind.LOCAL, handler=make_help_handler(reg)),
        Command(name="memory", description="列出已加载的项目/用户记忆文件", kind=Kind.LOCAL, handler=handle_memory),
        Command(name="permission", description="显示当前权限模式", kind=Kind.LOCAL, handler=handle_permission),
        Command(name="plan", description="切换到计划模式（仅只读工具）", kind=Kind.UI, handler=handle_plan),
        Command(name="resume", description="从历史会话恢复", kind=Kind.UI, handler=handle_resume),
        Command(name="review", description="请求 LLM 审查当前上下文中的代码", kind=Kind.PROMPT, handler=handle_review),
        Command(name="session", description="显示当前会话标识与存档路径", kind=Kind.LOCAL, handler=handle_session),
        Command(name="status", description="显示模式/用量/工具/记忆/模型/目录概览", kind=Kind.LOCAL, handler=handle_status),
    ]
    for cmd in items:
        reg.register(cmd)


__all__ = ["REVIEW_DIRECTIVE", "register_builtins"]
