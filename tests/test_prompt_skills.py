"""prompt.skills_block 与 build_system_prompt 第三参冒烟测试。"""

from __future__ import annotations

from nuocode.prompt import build_system_prompt
from nuocode.prompt.skills_block import (
    ActiveSkillEntry,
    SkillCatalogItem,
    render_active_skills_block,
    render_skills_catalog,
)


def test_render_skills_catalog_empty() -> None:
    assert render_skills_catalog([]) == ""


def test_render_skills_catalog_non_empty() -> None:
    out = render_skills_catalog([SkillCatalogItem("commit", "do commit")])
    assert "Available Skills" in out
    assert "commit: do commit" in out
    assert "LoadSkill" in out


def test_render_active_skills_block_empty() -> None:
    assert render_active_skills_block([]) == ""


def test_render_active_skills_block_non_empty() -> None:
    out = render_active_skills_block([ActiveSkillEntry("review", "REVIEW SOP")])
    assert "Active Skills" in out
    assert "Skill: review" in out
    assert "REVIEW SOP" in out


def test_build_system_prompt_with_skills_catalog() -> None:
    text = build_system_prompt("", "", "## Available Skills\n- x: y")
    assert "Available Skills" in text
    # 与默认相同三空槽时不应包含 catalog
    assert "Available Skills" not in build_system_prompt("", "")


def test_build_system_prompt_default_backcompat() -> None:
    # 旧 (X, Y) 调用方式仍可用
    a = build_system_prompt("", "")
    b = build_system_prompt()
    assert a == b
