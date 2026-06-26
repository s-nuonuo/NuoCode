"""TeamDelete 工具（chap15 F22-F23）。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from nuocode.tool import Result

if TYPE_CHECKING:
    from nuocode.team.manager import Manager


class TeamDeleteTool:
    """删除 Team（F22-F23）。"""

    read_only = False

    def __init__(self, manager: Manager) -> None:
        self._manager = manager

    def name(self) -> str:
        return "TeamDelete"

    def description(self) -> str:
        return (
            "删除一个 Team。\n"
            "- 有活跃成员时默认拒绝，使用 force=true 强制删除\n"
            "- 删除时自动清理队员 worktree 和 session 目录"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "team_name": {
                    "type": "string",
                    "description": "要删除的团队名称（必填）",
                },
                "force": {
                    "type": "boolean",
                    "description": "是否强制删除，有活跃成员时需要 true",
                },
            },
            "required": ["team_name"],
        }

    async def execute(self, args: str, ctx: Any = None) -> Result:  # noqa: ARG002
        try:
            params = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError):
            return Result(content="[TeamDelete] 参数解析失败", is_error=True)

        team_name = params.get("team_name") or ""
        force = bool(params.get("force", False))

        if not team_name:
            return Result(content="[TeamDelete] team_name 不能为空", is_error=True)

        from nuocode.team.types import TeamHasActiveMembersError, TeamNotFoundError

        try:
            await self._manager.delete(team_name, force=force)
        except TeamNotFoundError as e:
            return Result(content=f"[TeamDelete] 失败: {e}", is_error=True)
        except TeamHasActiveMembersError as e:
            return Result(content=f"[TeamDelete] 失败: {e}", is_error=True)
        except Exception as e:  # noqa: BLE001
            return Result(content=f"[TeamDelete] 失败: {e}", is_error=True)

        return Result(content=f"Team {team_name!r} 已成功删除")
