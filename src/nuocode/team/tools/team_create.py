"""TeamCreate 工具（chap15 F20-F21）。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from nuocode.tool import Result

if TYPE_CHECKING:
    from nuocode.team.manager import Manager


class TeamCreateTool:
    """创建 Team（F20-F21）。"""

    read_only = False

    def __init__(self, manager: Manager) -> None:
        self._manager = manager

    def name(self) -> str:
        return "TeamCreate"

    def description(self) -> str:
        return (
            "创建一个 Agent 团队（Team）。\n"
            "- 自动检测后端（tmux/iterm2/in-process）\n"
            "- 同名团队自动后缀 -2/-3 避免冲突\n"
            "返回 {team_name, backend, config_path}"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "team_name": {
                    "type": "string",
                    "description": "团队名称（必填），经 sanitize 后做为目录名",
                },
                "description": {
                    "type": "string",
                    "description": "团队描述（可选）",
                },
                "agent_type": {
                    "type": "string",
                    "description": "保留字段（本期不使用）",
                },
            },
            "required": ["team_name"],
        }

    async def execute(self, args: str, ctx: Any = None) -> Result:  # noqa: ARG002
        try:
            params = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError):
            return Result(content="[TeamCreate] 参数解析失败", is_error=True)

        team_name = params.get("team_name") or ""
        description = params.get("description") or ""

        if not team_name:
            return Result(content="[TeamCreate] team_name 不能为空", is_error=True)

        try:
            team = await self._manager.create(team_name, description)
        except ValueError as e:
            return Result(content=f"[TeamCreate] 失败: {e}", is_error=True)

        return Result(
            content=json.dumps(
                {
                    "team_name": team.sanitized_name,
                    "backend": str(team.backend),
                    "config_path": team.config_path,
                },
                ensure_ascii=False,
            )
        )
