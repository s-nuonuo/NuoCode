"""2 条提示词命令：/do /review。"""

from __future__ import annotations

from nuocode import prompt as prompt_mod
from nuocode.command.ui import UI
from nuocode.permission import Mode

REVIEW_DIRECTIVE = (
    "请审查当前上下文中的代码变更/已读取的文件，"
    "指出潜在 bug、可读性问题以及可简化处。"
)


async def handle_do(ui: UI) -> None:
    ui.set_mode(Mode.DEFAULT)
    ui.inject_and_send("/do", prompt_mod.EXECUTE_DIRECTIVE)


async def handle_review(ui: UI) -> None:
    ui.inject_and_send("/review", REVIEW_DIRECTIVE)


__all__ = ["REVIEW_DIRECTIVE", "handle_do", "handle_review"]
