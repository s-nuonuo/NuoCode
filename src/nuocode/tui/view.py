"""TUI 渲染拼装：用户/助手/错误块、状态栏、待批准块。"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from nuocode.permission import Mode

# 模式 → (短标签, 颜色)
_MODE_BADGE: dict[Mode, tuple[str, str]] = {
    Mode.DEFAULT: ("DEFAULT", "bold green"),
    Mode.ACCEPT_EDITS: ("ACCEPT EDITS", "bold cyan"),
    Mode.PLAN: ("PLAN", "bold yellow"),
    Mode.BYPASS: ("BYPASS", "bold red"),
}


def mode_badge(mode: Mode) -> tuple[str, str]:
    return _MODE_BADGE.get(mode, ("DEFAULT", "bold green"))


def user_block(text: str) -> RenderableType:
    return Text(f"❯ {text}", style="bold cyan")


def assistant_block(reply: str) -> RenderableType:
    return Group(Text("● ", style="bold green", end=""), Markdown(reply))


def error_block(err: BaseException) -> RenderableType:
    return Text(f"● {err}", style="bold red")


def notice_block(text: str) -> RenderableType:
    return Text(f"● {text}", style="dim")


def _fmt_tok(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.1f}M"


def status_line(
    mode: Mode,
    model: str,
    width: int = 80,
    usage_in: int = 0,
    usage_out: int = 0,
) -> RenderableType:
    """状态栏：左侧常驻模式徽标（取代 provider 名）；右侧模型名 + 累计用量。"""
    table = Table.grid(expand=True)
    table.add_column(justify="left", ratio=1)
    table.add_column(justify="right", ratio=1)
    label, style = mode_badge(mode)
    left = Text(label, style=style)
    right = Text(f"{model}", style="dim")
    if usage_in or usage_out:
        right.append(f"  ↑{_fmt_tok(usage_in)} ↓{_fmt_tok(usage_out)} tok", style="dim")
    table.add_row(left, right)
    return table


def tool_line(name: str, args: str) -> RenderableType:
    return Text.assemble(
        ("● ", "bold cyan"),
        (f"{name}", "bold"),
        ("(", "dim"),
        (args, "dim"),
        (")", "dim"),
    )


def tool_result_summary(result: str, is_error: bool, max_lines: int = 8) -> RenderableType:
    lines = result.splitlines() if result else ["(empty)"]
    truncated = False
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
    body = "\n".join(lines)
    if truncated:
        body += "\n…"
    style = "red" if is_error else "dim"
    text = Text("⎿ " + body, style=style)
    return Padding(text, (0, 0, 0, 2))


# ───────── 待批准块（chap06） ─────────

_APPROVAL_OPTIONS = [
    "1. 允许本次",
    "2. 永久允许（写入本地配置）",
    "3. 拒绝本次",
]


def approval_block(name: str, args: str, reason: str, cursor: int) -> RenderableType:
    """多行待批准块：动作名 + 参数预览 + 触发原因 + 三选菜单（光标高亮）。"""
    parts: list[RenderableType] = []
    head = Text.assemble(
        ("● ", "bold yellow"),
        ("待批准: ", "bold yellow"),
        (name, "bold"),
        ("(", "dim"),
        (args, "dim"),
        (")", "dim"),
    )
    parts.append(head)
    if reason:
        parts.append(Padding(Text(reason, style="dim"), (0, 0, 0, 2)))
    parts.append(Padding(Text("是否继续?", style="bold"), (0, 0, 0, 2)))
    for i, label in enumerate(_APPROVAL_OPTIONS):
        if i == cursor:
            line = Text(f"> {label}", style="bold yellow")
        else:
            line = Text(f"  {label}", style="dim")
        parts.append(Padding(line, (0, 0, 0, 2)))
    parts.append(
        Padding(
            Text("↑↓ 选择 · 回车确认 · Esc 取消", style="dim"),
            (0, 0, 0, 2),
        )
    )
    return Group(*parts)
