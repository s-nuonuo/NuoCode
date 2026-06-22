"""把 Skill catalog 注册为 PROMPT 命令：/<skill_name> [args] 触发 Executor。"""

from __future__ import annotations

from nuocode.command.command import Command, Kind
from nuocode.command.registry import Registry
from nuocode.command.ui import UI
from nuocode.skills.catalog import Catalog


def _make_handler(skill_name: str):
    async def _h(ui: UI) -> None:
        ui.inject_and_send(
            f"/{skill_name}",
            f'Activate skill "{skill_name}" by calling LoadSkill, then follow its SOP.',
        )

    _h.__name__ = f"_skill_{skill_name}_handler"
    return _h


def register_skills_as_commands(reg: Registry, catalog: Catalog) -> int:
    """先清除所有 is_skill=True 的旧条目，再按 catalog 字典序注册。返回新增数量。"""
    reg.remove_if(lambda c: getattr(c, "is_skill", False))
    count = 0
    for sk in catalog.list():
        if reg.lookup(sk.meta.name) is not None:
            continue
        cmd = Command(
            name=sk.meta.name,
            description=sk.meta.description,
            kind=Kind.PROMPT,
            handler=_make_handler(sk.meta.name),
            is_skill=True,
        )
        try:
            reg.register(cmd)
            count += 1
        except RuntimeError:
            continue
    return count


__all__ = ["register_skills_as_commands"]
