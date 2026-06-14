"""TUI 渲染拼装：用户/助手/错误块、状态栏。"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.padding import Padding
from rich.table import Table
from rich.text import Text


def user_block(text: str) -> RenderableType:
    """用户输入块。"""
    return Text(f"❯ {text}", style="bold cyan")


def assistant_block(reply: str) -> RenderableType:
    """助手回复块（done 后整段 markdown 渲染）。"""
    return Group(Text("● ", style="bold green", end=""), Markdown(reply))


def error_block(err: BaseException) -> RenderableType:
    """错误块（红色高亮）。"""
    return Text(f"● {err}", style="bold red")


def _fmt_tok(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.1f}M"


def status_line(
    provider_name: str,
    model: str,
    width: int = 80,
    plan_mode: bool = False,
    usage_in: int = 0,
    usage_out: int = 0,
) -> RenderableType:
    """状态栏：左 provider 名（+PLAN 徽标）、右 model 名 + 累计用量。"""
    table = Table.grid(expand=True)
    table.add_column(justify="left", ratio=1)
    table.add_column(justify="right", ratio=1)
    left = Text(provider_name, style="bold magenta")
    if plan_mode:
        left.append("  [PLAN]", style="bold yellow")
    right = Text(f"{model}", style="dim")
    if usage_in or usage_out:
        right.append(f"  ↑{_fmt_tok(usage_in)} ↓{_fmt_tok(usage_out)} tok", style="dim")
    table.add_row(left, right)
    return table


# ───────── chap03 工具行 ─────────


def tool_line(name: str, args: str) -> RenderableType:
    """工具调用行：``● name(args)``，Claude Code 风格。"""
    return Text.assemble(
        ("● ", "bold cyan"),
        (f"{name}", "bold"),
        ("(", "dim"),
        (args, "dim"),
        (")", "dim"),
    )


def tool_result_summary(result: str, is_error: bool, max_lines: int = 8) -> RenderableType:
    """工具结果摘要：缩进 + ⎿ 前缀；UI 截断到 ``max_lines`` 行。"""
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
