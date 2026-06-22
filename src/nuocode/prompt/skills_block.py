"""chap11: Skill 两阶段提示渲染（catalog 第一阶段 + active 第二阶段）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillCatalogItem:
    name: str
    description: str


@dataclass(frozen=True)
class ActiveSkillEntry:
    name: str
    body: str


def render_skills_catalog(items: list[SkillCatalogItem]) -> str:
    """第一阶段：system prompt 中的 Skill 列表（name+description）。"""
    if not items:
        return ""
    lines = ["## Available Skills", ""]
    for it in items:
        lines.append(f"- {it.name}: {it.description}")
    lines.append("")
    lines.append(
        'Call the LoadSkill tool with {"name": "<skill_name>"} to activate a skill\'s '
        "full SOP and specialized tools before executing it."
    )
    return "\n".join(lines)


def render_active_skills_block(entries: list[ActiveSkillEntry]) -> str:
    """第二阶段：env context 中的已激活 Skill SOP 拼接。"""
    if not entries:
        return ""
    parts = ["## Active Skills"]
    for e in entries:
        parts.append("")
        parts.append(f"### Skill: {e.name}")
        parts.append("")
        parts.append(e.body.rstrip())
    return "\n".join(parts)


__all__ = [
    "ActiveSkillEntry",
    "SkillCatalogItem",
    "render_active_skills_block",
    "render_skills_catalog",
]
