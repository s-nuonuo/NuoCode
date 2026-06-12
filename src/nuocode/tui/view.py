"""TUI 渲染拼装：用户/助手/错误块、状态栏。"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.markdown import Markdown
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


def status_line(provider_name: str, model: str, width: int = 80) -> RenderableType:
    """状态栏：左 provider 名、右 model 名。"""
    table = Table.grid(expand=True)
    table.add_column(justify="left", ratio=1)
    table.add_column(justify="right", ratio=1)
    table.add_row(
        Text(provider_name, style="bold magenta"),
        Text(model, style="dim"),
    )
    return table
