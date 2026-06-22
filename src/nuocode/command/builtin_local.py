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


async def handle_skill(ui: UI) -> None:
    """chap11 ``/skill``：列出 Catalog 与已激活 Skill。"""
    items = ui.list_catalog_skills()
    active = set(ui.list_active_skills())
    if not items:
        ui.println("未发现任何 Skill")
        return
    lines = ["Skill Catalog:"]
    name_w = max(len(n) for n, _, _ in items)
    for name, source, desc in items:
        marker = "*" if name in active else " "
        src_label = f"[{source}]".ljust(10)
        lines.append(f" {marker} /{name.ljust(name_w)}  {src_label} {desc}")
    if active:
        lines.append("")
        lines.append("已激活: " + ", ".join(sorted(active)))
    ui.println("\n".join(lines))


__all__ = [
    "handle_memory",
    "handle_permission",
    "handle_session",
    "handle_skill",
    "handle_status",
    "make_help_handler",
]
