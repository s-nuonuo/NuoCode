"""TaskList 工具（chap15 F28）。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from nuocode.tool import Result

if TYPE_CHECKING:
    from nuocode.team.manager import Manager


class TaskListTool:
    """列出任务（F28）。仅 Team 队员可用。"""

    read_only = True

    def __init__(self, manager: Manager) -> None:
        self._manager = manager

    def name(self) -> str:
        return "TaskList"

    def description(self) -> str:
        return (
            "列出 Team 共享任务列表（仅 Team 队员可用）。\n"
            "返回带 is_ready 字段的任务数组（is_ready=true 表示无未完成 blocker）。"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "blocked"],
                    "description": "按状态过滤（可选），不填返回全部",
                },
            },
        }

    async def execute(self, args: str, ctx: Any = None) -> Result:
        try:
            params = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError):
            return Result(content="[TaskList] 参数解析失败", is_error=True)

        status = params.get("status") or None

        team = self._get_team(ctx)
        if team is None:
            return Result(content="[TaskList] 无法获取当前 Team 上下文", is_error=True)

        from nuocode.team.tasks import Filter, Store

        f = Filter(status=status)
        store = Store(team.tasks_path)
        try:
            tasks = await store.list_(f)
        except Exception as e:  # noqa: BLE001
            return Result(content=f"[TaskList] 失败: {e}", is_error=True)

        return Result(content=json.dumps(tasks, ensure_ascii=False))

    def _get_team(self, ctx: Any) -> Any:
        from nuocode.agent.team_hook import teammate_context_from_ctx
        tc = teammate_context_from_ctx(ctx)
        if tc is None:
            teams = self._manager.list_()
            return teams[0] if teams else None
        return self._manager.get(tc.team_name)
