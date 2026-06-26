"""TaskUpdate 工具（chap15 F29）。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from nuocode.tool import Result

if TYPE_CHECKING:
    from nuocode.team.manager import Manager


class TaskUpdateTool:
    """更新任务（F29）。仅 Team 队员可用。"""

    read_only = False

    def __init__(self, manager: Manager) -> None:
        self._manager = manager

    def name(self) -> str:
        return "TaskUpdate"

    def description(self) -> str:
        return (
            "更新 Team 共享任务（仅 Team 队员可用）。\n"
            "支持 add_blocks/add_blocked_by 双向依赖维护。"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "任务 ID（必填）",
                },
                "title": {"type": "string", "description": "新标题（可选）"},
                "description": {"type": "string", "description": "新描述（可选）"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "blocked"],
                    "description": "新状态（可选）",
                },
                "assignee": {"type": "string", "description": "新指派人（可选）"},
                "add_blocks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "新增阻塞关系（此任务阻塞哪些）",
                },
                "add_blocked_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "新增被阻塞关系（此任务被哪些阻塞）",
                },
                "remove_blocks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "移除阻塞关系",
                },
                "remove_blocked_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "移除被阻塞关系",
                },
            },
            "required": ["task_id"],
        }

    async def execute(self, args: str, ctx: Any = None) -> Result:
        try:
            params = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError):
            return Result(content="[TaskUpdate] 参数解析失败", is_error=True)

        task_id = params.get("task_id") or ""
        if not task_id:
            return Result(content="[TaskUpdate] task_id 不能为空", is_error=True)

        team = self._get_team(ctx)
        if team is None:
            return Result(content="[TaskUpdate] 无法获取当前 Team 上下文", is_error=True)

        from nuocode.team.tasks import Patch, Store

        patch = Patch(
            title=params.get("title"),
            description=params.get("description"),
            status=params.get("status"),
            assignee=params.get("assignee"),
            add_blocks=list(params.get("add_blocks") or []),
            add_blocked_by=list(params.get("add_blocked_by") or []),
            remove_blocks=list(params.get("remove_blocks") or []),
            remove_blocked_by=list(params.get("remove_blocked_by") or []),
        )

        store = Store(team.tasks_path)
        try:
            await store.update(task_id, patch)
        except KeyError:
            return Result(content=f"[TaskUpdate] 任务不存在: {task_id!r}", is_error=True)
        except Exception as e:  # noqa: BLE001
            return Result(content=f"[TaskUpdate] 失败: {e}", is_error=True)

        return Result(content=json.dumps({"task_id": task_id, "status": "updated"}, ensure_ascii=False))

    def _get_team(self, ctx: Any) -> Any:
        from nuocode.agent.team_hook import teammate_context_from_ctx
        tc = teammate_context_from_ctx(ctx)
        if tc is None:
            teams = self._manager.list_()
            return teams[0] if teams else None
        return self._manager.get(tc.team_name)
