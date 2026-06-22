"""skills 包：Skill 数据结构 + Catalog + ActiveSkills + Executor + InstallSkill。"""

from __future__ import annotations

from nuocode.skills.active import ActiveSkills
from nuocode.skills.adapter import (
    PromptEntry,
    PromptItem,
    active_to_prompt_entries,
    catalog_to_prompt_items,
)
from nuocode.skills.catalog import Catalog, ValidationIssue
from nuocode.skills.executor import ExecuteEvent, ExecuteRequest, Executor
from nuocode.skills.parser import parse_skill_dir
from nuocode.skills.render import render_body
from nuocode.skills.types import ActiveEntry, Skill, SkillMeta, SkillSource, ToolSpec

__all__ = [
    "ActiveEntry",
    "ActiveSkills",
    "Catalog",
    "ExecuteEvent",
    "ExecuteRequest",
    "Executor",
    "PromptEntry",
    "PromptItem",
    "Skill",
    "SkillMeta",
    "SkillSource",
    "ToolSpec",
    "ValidationIssue",
    "active_to_prompt_entries",
    "catalog_to_prompt_items",
    "parse_skill_dir",
    "render_body",
]
