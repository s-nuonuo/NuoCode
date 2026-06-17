"""TUI 命令派发：把以 ``/`` 开头的输入路由到具体动作。

所有命令都在主事件循环里同步派发；耗时动作（如 ``/compact``）由命令实现自己起 task。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nuocode.tui.app import NuoCodeApp


# ───────── 各命令 handler ─────────


def _cmd_exit(app: NuoCodeApp, _arg: str) -> bool:
    app.exit()
    return True


def _cmd_plan(app: NuoCodeApp, _arg: str) -> bool:
    from textual.widgets import RichLog

    from nuocode.permission import Mode

    app.mode = Mode.PLAN
    log = app.query_one("#log", RichLog)
    log.write("● 已进入计划模式（仅只读工具）。用 /do 切回并执行。")
    app._refresh_statusbar()
    return True


def _cmd_do(app: NuoCodeApp, _arg: str) -> bool:
    """``/do``：切回 DEFAULT 并向对话注入 EXECUTE_DIRECTIVE，触发一次 turn。"""
    from textual.widgets import RichLog

    from nuocode import prompt as prompt_mod
    from nuocode.permission import Mode
    from nuocode.tui.view import user_block

    app.mode = Mode.DEFAULT
    log = app.query_one("#log", RichLog)
    app.conv.add_user(prompt_mod.EXECUTE_DIRECTIVE)
    log.write(user_block(prompt_mod.EXECUTE_DIRECTIVE))
    app._start_turn()
    return True


def _cmd_compact(app: NuoCodeApp, _arg: str) -> bool:
    """``/compact``：手动触发一次摘要压缩。"""
    if app.agent is None:
        return True
    app.start_force_compact()
    return True


def _cmd_resume(app: NuoCodeApp, _arg: str) -> bool:
    """``/resume``：进入会话恢复列表。仅 IDLE 可用。"""
    from textual.widgets import RichLog

    from nuocode.tui.app import SessionState

    if app.state is not SessionState.IDLE:
        log = app.query_one("#log", RichLog)
        log.write("● 请等待当前任务完成。")
        return True
    from nuocode.tui import resume as resume_mod

    resume_mod.begin_resume(app)
    return True


_REGISTRY: dict[str, callable] = {
    "/exit": _cmd_exit,
    "/plan": _cmd_plan,
    "/do": _cmd_do,
    "/compact": _cmd_compact,
    "/resume": _cmd_resume,
}


def is_command(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("/")


def dispatch(app: NuoCodeApp, text: str) -> bool:
    """匹配命令并执行；返回 True 表示已处理，调用方不再走默认 user 提交。

    未识别的 ``/xxx`` 也返回 True 并在 log 中提示，避免被当成普通对话发出去。
    """
    from textual.widgets import RichLog

    stripped = text.strip()
    if not stripped.startswith("/"):
        return False

    # 支持 "/cmd arg1 arg2" 形式
    parts = stripped.split(maxsplit=1)
    name = parts[0]
    arg = parts[1] if len(parts) > 1 else ""

    handler = _REGISTRY.get(name)
    if handler is None:
        log = app.query_one("#log", RichLog)
        log.write(f"● 未知命令: {name}")
        return True
    return handler(app, arg)


__all__ = ["dispatch", "is_command"]
