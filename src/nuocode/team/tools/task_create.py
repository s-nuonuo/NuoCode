"""TaskCreate 工具（chap15 F26）。"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from nuocode.tool import Result

if TYPE_CHECKING:
    from nuocode.team.manager import Manager


class TaskCreateTool:
    """创建任务（F26）。仅 Team 队员可用。"""

    read_only = False

    def __init__(self, manager: Manager) -> None:
        self._manager = manager

    def name(self) -> str:
        return "TaskCreate"

    def description(self) -> str:
        return (
            "在 Team 共享任务列表中创建新任务（仅 Team 队员可用）。\n"
            "返回 {task_id}"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "任务标题（必填）",
                },
                "description": {
                    "type": "string",
                    "description": "任务描述（可选）",
                },
                "assignee": {
                    "type": "string",
                    "description": "指派的队员名（可选）",
                },
                "blocked_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "被哪些任务 id 阻塞（可选）",
                },
            },
            "required": ["title"],
        }

    async def execute(self, args: str, ctx: Any = None) -> Result:
        try:
            params = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError):
            return Result(content="[TaskCreate] 参数解析失败", is_error=True)

        title = params.get("title") or ""
        if not title:
            return Result(content="[TaskCreate] title 不能为空", is_error=True)

        team = self._get_team(ctx)
        if team is None:
            return Result(content="[TaskCreate] 无法获取当前 Team 上下文", is_error=True)

        from nuocode.team.tasks import Status, Store, Task

        task = Task(
            id="",  # 由 Store.create 填充
            title=title,
            description=params.get("description") or "",
            status=Status.PENDING,
            assignee=params.get("assignee") or "",
            blocked_by=list(params.get("blocked_by") or []),
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )

        store = Store(team.tasks_path)
        try:
            task_id = await store.create(task)
        except Exception as e:  # noqa: BLE001
            return Result(content=f"[TaskCreate] 创建失败: {e}", is_error=True)

        return Result(content=json.dumps({"task_id": task_id}, ensure_ascii=False))

    def _get_team(self, ctx: Any) -> Any:
        """从 ctx 获取当前 Team。"""
        from nuocode.agent.team_hook import teammate_context_from_ctx
        tc = teammate_context_from_ctx(ctx)
        if tc is None:
            # 主 Agent 调用时走 active team（第一个 team）
            teams = self._manager.list_()
            return teams[0] if teams else None

        # 通过 team_name 找 Team
        return self._manager.get(tc.team_name)
