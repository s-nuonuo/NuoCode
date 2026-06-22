"""Registry.remove_if + skills_register 冒烟测试。"""

from __future__ import annotations

from pathlib import Path

from nuocode.command.command import Command, Kind
from nuocode.command.registry import Registry
from nuocode.command.skills_register import register_skills_as_commands
from nuocode.skills import Catalog, SkillSource, parse_skill_dir


def _noop_handler():
    async def _h(_ui):
        return None

    return _h


def test_remove_if_pred() -> None:
    r = Registry()
    r.register(Command(name="a", description="x", kind=Kind.LOCAL, handler=_noop_handler()))
    r.register(
        Command(
            name="b",
            description="x",
            kind=Kind.LOCAL,
            handler=_noop_handler(),
            is_skill=True,
        )
    )
    n = r.remove_if(lambda c: c.is_skill)
    assert n == 1
    assert r.lookup("a") is not None
    assert r.lookup("b") is None


def test_register_skills_as_commands(tmp_path: Path) -> None:
    sd = tmp_path / "alpha"
    sd.mkdir()
    (sd / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: AAA\n---\n\nBody\n", encoding="utf-8"
    )
    sk = parse_skill_dir(sd, SkillSource.USER)
    cat = Catalog()
    cat.register(sk)
    reg = Registry()
    n = register_skills_as_commands(reg, cat)
    assert n == 1
    cmd = reg.lookup("alpha")
    assert cmd is not None and cmd.is_skill is True
    # 二次注册：应清空旧条目，重新注册
    n2 = register_skills_as_commands(reg, cat)
    assert n2 == 1
