"""TUI 命令分发：``/`` 开头输入 → command Registry 查找 → 调用 handler。

- 旧版的 `is_command/dispatch` 已被新分发器替换。
- App 实现 ``command.UI`` Protocol 的方法在 ``app.py`` 中按照接口要求逐个补齐。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nuocode.command import Kind, parse

if TYPE_CHECKING:
    from nuocode.tui.app import NuoCodeApp

UNKNOWN_HINT = "未知命令: 输入 /help 查看可用命令"


async def dispatch_slash(app: NuoCodeApp, text: str) -> bool:
    """处理一行输入：返回 True 表示已被命令系统消费（无论成功/失败/未命中）。

    - 非 ``/`` 开头：返回 False，由调用方继续走 ``conv.add_user`` + ``begin_turn``。
    - ``/foo``：命中则 await 其 handler；未命中则打印未知命令提示。
    - ``Kind.UI`` / ``Kind.PROMPT`` 命令在非 idle 状态被拒绝并提示。
    """
    name, is_slash = parse(text)
    if not is_slash:
        return False

    from nuocode.tui.app import SessionState
    from nuocode.tui.view import error_block, notice_block

    log = app._cmd_log()
    reg = app.cmd_registry
    if reg is None:
        log.write(error_block(RuntimeError("命令注册中心未初始化")))
        return True

    cmd = reg.lookup(name)
    if cmd is None:
        log.write(notice_block(UNKNOWN_HINT))
        return True

    if cmd.kind in (Kind.UI, Kind.PROMPT) and app.state is not SessionState.IDLE:
        log.write(error_block(RuntimeError("请等待当前任务完成")))
        return True

    try:
        await cmd.handler(app)
    except Exception as exc:  # noqa: BLE001
        log.write(error_block(exc))
    return True


__all__ = ["UNKNOWN_HINT", "dispatch_slash"]
