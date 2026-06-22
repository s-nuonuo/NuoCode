"""5 条纯本地命令：/help /status /memory /permission /session。"""

from __future__ import annotations

from nuocode.command.command import Handler
from nuocode.command.registry import Registry
from nuocode.command.ui import UI


def make_help_handler(reg: Registry) -> Handler:
    """``/help`` 工厂：闭包捕获 reg。

    输出按 ``name`` 字典序排列的"/<name>  <description>" 两列对齐列表。
    """

    async def _help(ui: UI) -> None:
        cmds = reg.visible()
        if not cmds:
            ui.println("(无可用命令)")
            return
        w = max(len(c.name) for c in cmds) + 1  # +1 for "/"
        lines = [f"/{c.name.ljust(w - 1)}  {c.description}" for c in cmds]
        ui.println("\n".join(lines))

    return _help


_STATUS_KEYS = ["Mode", "Tokens", "Tools", "Memories", "Model", "Directory"]
_KEY_W = max(len(k) for k in _STATUS_KEYS) + 1  # +1 for ":"


def _row(key: str, value: str) -> str:
    return f"{(key + ':').ljust(_KEY_W + 1)} {value}"


async def handle_status(ui: UI) -> None:
    files = ui.memory_files()
    rows = [
        "nuocode Status",
        "",
        _row("Mode", ui.mode.value),
        _row("Tokens", f"{ui.usage_in} in / {ui.usage_out} out"),
        _row("Tools", f"{ui.tool_count()} enabled"),
        _row("Memories", f"{len(files)} files"),
        _row("Model", ui.model_name() or "(none)"),
        _row("Directory", ui.cwd() or "(unknown)"),
    ]
    ui.println("\n".join(rows))


async def handle_memory(ui: UI) -> None:
    files = ui.memory_files()
    if not files:
        ui.println("无已加载的记忆文件")
        return
    ui.println("\n".join(files))


async def handle_permission(ui: UI) -> None:
    ui.println(ui.mode.value)


async def handle_session(ui: UI) -> None:
    sid = ui.session_id() or "(none)"
    path = ui.session_path() or "(none)"
    ui.println(f"Session: {sid}\nPath: {path}")


__all__ = [
    "handle_memory",
    "handle_permission",
    "handle_session",
    "handle_status",
    "make_help_handler",
]
