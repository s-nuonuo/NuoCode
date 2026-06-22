"""InstallSkill 工具：远程 zip → ~/.nuocode/skills/<name>/。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nuocode.skills.catalog import Catalog
from nuocode.skills.install import install_from_url
from nuocode.tool import Result


class InstallSkillTool:
    read_only = False
    is_system = True

    def __init__(self, catalog: Catalog, work_dir: Path) -> None:
        self._catalog = catalog
        self._work_dir = Path(work_dir)

    def name(self) -> str:
        return "install_skill"

    def description(self) -> str:
        return (
            "Install a remote Skill bundle from a zip URL into the user-level skills directory. "
            "After install the catalog is reloaded and the new Skill becomes selectable."
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "http(s)://... or file://... pointing to a Skill zip bundle.",
                },
            },
            "required": ["source"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        source = data.get("source")
        if not isinstance(source, str) or not source:
            return Result(content="source 参数缺失", is_error=True)
        try:
            name = await install_from_url(source, self._catalog, self._work_dir)
        except Exception as e:  # noqa: BLE001
            return Result(content=f"install skill failed: {e}", is_error=True)
        return Result(content=f"Skill {name} installed and catalog reloaded.")


__all__ = ["InstallSkillTool"]
