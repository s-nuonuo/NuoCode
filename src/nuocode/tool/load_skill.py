"""LoadSkill 工具：把 Skill SOP 钉到 env context + 注册专属工具。"""

from __future__ import annotations

import json
import sys
from typing import Any

from nuocode.skills.active import ActiveSkills
from nuocode.skills.catalog import Catalog
from nuocode.tool import Registry, Result
from nuocode.tool.skill_tool import new_skill_tool


class LoadSkillTool:
    read_only = True
    is_system = True

    def __init__(self, catalog: Catalog, active: ActiveSkills, registry: Registry) -> None:
        self._catalog = catalog
        self._active = active
        self._registry = registry

    def name(self) -> str:
        return "load_skill"

    def description(self) -> str:
        return (
            "Activate a Skill: pin its SOP to environment context and register its specialized tools. "
            "Call this tool with {\"name\": \"<skill_name>\"} after seeing a relevant skill in the "
            "Available Skills list. After activation the Skill body becomes part of every subsequent "
            "system context until /clear."
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name (must match an entry in Available Skills).",
                },
            },
            "required": ["name"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        name = data.get("name")
        if not isinstance(name, str) or not name:
            return Result(content="name 参数缺失", is_error=True)
        skill = self._catalog.get(name)
        if skill is None:
            return Result(content=f"unknown skill: {name}", is_error=True)
        # 重读磁盘最新 body（容错回退）
        body = skill.prompt_body
        try:
            md = (skill.source_dir / "SKILL.md").read_text(encoding="utf-8")
            from nuocode.skills.parser import (
                _parse_frontmatter_and_body,  # type: ignore[attr-defined]
            )

            _, fresh_body = _parse_frontmatter_and_body(md)
            body = fresh_body
        except Exception as e:  # noqa: BLE001
            print(f"[skills] warn: re-read SKILL.md for {name} failed: {e}", file=sys.stderr)

        self._active.activate(skill.meta.name, body)

        registered = 0
        for spec in skill.tool_specs:
            tool = new_skill_tool(
                spec.name, spec.description, spec.input_schema, spec.command, spec.base_dir
            )
            self._registry.register_skill_tool(tool)
            registered += 1

        return Result(
            content=(
                f"Skill {name} activated. SOP pinned to env context. "
                f"{registered} specialized tools registered."
            )
        )


__all__ = ["LoadSkillTool"]
