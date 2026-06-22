"""提示词命令：/do（/review 已迁移为 Skill）。"""

from __future__ import annotations

from nuocode import prompt as prompt_mod
from nuocode.command.ui import UI
from nuocode.permission import Mode


async def handle_do(ui: UI) -> None:
    ui.set_mode(Mode.DEFAULT)
    ui.inject_and_send("/do", prompt_mod.EXECUTE_DIRECTIVE)


__all__ = ["handle_do"]
