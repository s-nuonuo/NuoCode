"""TaskGet 工具（chap15 F27）。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from nuocode.tool import Result

if TYPE_CHECKING:
    from nuocode.team.manager import Manager


class TaskGetTool:
    """获取任务详情（F27）。仅 Team 队员可用。"""

    read_only = True

    def __init__(self, manager: Manager) -> None:
        self._manager = manager

    def name(self) -> str:
        return "TaskGet"

    def description(self) -> str:
        return "获取指定任务详情（仅 Team 队员可用）。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "任务 ID（必填）",
                },
            },
            "required": ["task_id"],
        }

    async def execute(self, args: str, ctx: Any = None) -> Result:
        try:
            params = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError):
            return Result(content="[TaskGet] 参数解析失败", is_error=True)

        task_id = params.get("task_id") or ""
        if not task_id:
            return Result(content="[TaskGet] task_id 不能为空", is_error=True)

        team = self._get_team(ctx)
        if team is None:
            return Result(content="[TaskGet] 无法获取当前 Team 上下文", is_error=True)

        from nuocode.team.tasks import Store

        store = Store(team.tasks_path)
        try:
            task = await store.get(task_id)
        except KeyError:
            return Result(content=f"[TaskGet] 任务不存在: {task_id!r}", is_error=True)

        return Result(content=json.dumps(task.to_dict(), ensure_ascii=False))

    def _get_team(self, ctx: Any) -> Any:
        from nuocode.agent.team_hook import teammate_context_from_ctx
        tc = teammate_context_from_ctx(ctx)
        if tc is None:
            teams = self._manager.list_()
            return teams[0] if teams else None
        return self._manager.get(tc.team_name)
