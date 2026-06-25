"""后台任务工具：TaskList / TaskGet / TaskStop / SendMessage（chap13 F20）。

这 4 个工具面向主 Agent 暴露，让主 Agent 可以查询和操控后台任务。
所有工具需要 ``Manager`` 注入；注入通过构造函数或工厂函数完成。
"""

from __future__ import annotations

import json
from typing import Any

from nuocode.task.manager import (
    Manager,
)
from nuocode.tool import Result


class TaskListTool:
    """列出当前所有非终态后台任务（chap13 F20: TaskList）。"""

    read_only = True
    is_system = True

    def __init__(self, manager: Manager) -> None:
        self._mgr = manager

    def name(self) -> str:
        return "TaskList"

    def description(self) -> str:
        return "列出当前所有正在运行的后台子 Agent 任务（id/name/status/tool_count/last_activity）。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(self, args: str) -> Result:
        tasks = self._mgr.list(include_terminal=False)
        items = [
            {
                "id": t.id,
                "name": t.name or "",
                "status": t.status,
                "tool_count": t.tool_count,
                "last_activity": t.last_activity,
                "elapsed_s": round(t.elapsed, 1),
            }
            for t in tasks
        ]
        return Result(content=json.dumps(items, ensure_ascii=False, indent=2))


class TaskGetTool:
    """查询指定后台任务的完整状态（chap13 F20: TaskGet）。"""

    read_only = True
    is_system = True

    def __init__(self, manager: Manager) -> None:
        self._mgr = manager

    def name(self) -> str:
        return "TaskGet"

    def description(self) -> str:
        return "查询指定后台任务的完整状态，含 result/err。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "任务 ID（从 TaskList 或 Agent 工具返回值获取）",
                }
            },
            "required": ["task_id"],
        }

    async def execute(self, args: str) -> Result:
        try:
            params = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError):
            return Result(content="[TaskGet] 参数解析失败", is_error=True)

        task_id = params.get("task_id") or ""
        if not task_id:
            return Result(content="[TaskGet] task_id 不能为空", is_error=True)

        t = self._mgr.get(task_id)
        if t is None:
            return Result(content=f"[TaskGet] 未找到任务 {task_id!r}", is_error=True)

        data = {
            "id": t.id,
            "name": t.name or "",
            "status": t.status,
            "task": t.task,
            "result": t.result,
            "err": str(t.err) if t.err is not None else None,
            "tool_count": t.tool_count,
            "last_activity": t.last_activity,
            "elapsed_s": round(t.elapsed, 1),
        }
        return Result(content=json.dumps(data, ensure_ascii=False, indent=2))


class TaskStopTool:
    """取消指定后台任务（chap13 F20: TaskStop）。"""

    read_only = False
    is_system = True

    def __init__(self, manager: Manager) -> None:
        self._mgr = manager

    def name(self) -> str:
        return "TaskStop"

    def description(self) -> str:
        return "取消正在运行的后台任务。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "要取消的任务 ID",
                }
            },
            "required": ["task_id"],
        }

    async def execute(self, args: str) -> Result:
        try:
            params = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError):
            return Result(content="[TaskStop] 参数解析失败", is_error=True)

        task_id = params.get("task_id") or ""
        if not task_id:
            return Result(content="[TaskStop] task_id 不能为空", is_error=True)

        found = self._mgr.stop(task_id)
        if not found:
            return Result(content=f"[TaskStop] 未找到任务 {task_id!r}", is_error=True)

        return Result(
            content=json.dumps(
                {"task_id": task_id, "status": "cancellation_requested"},
                ensure_ascii=False,
            )
        )


class SendMessageTool:
    """向存活后台 Agent 续派任务（chap13 F20: SendMessage）。"""

    read_only = False
    is_system = True

    def __init__(self, manager: Manager) -> None:
        self._mgr = manager

    def name(self) -> str:
        return "SendMessage"

    def description(self) -> str:
        return (
            "向一个已完成的后台子 Agent（通过 name 标识）续派新任务，"
            "重新触发执行。"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "后台任务名称（Agent 工具的 name 字段）",
                },
                "message": {
                    "type": "string",
                    "description": "续发给子 Agent 的新任务消息",
                },
            },
            "required": ["name", "message"],
        }

    async def execute(self, args: str) -> Result:
        try:
            params = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError):
            return Result(content="[SendMessage] 参数解析失败", is_error=True)

        name = params.get("name") or ""
        message = params.get("message") or ""

        if not name:
            return Result(content="[SendMessage] name 不能为空", is_error=True)
        if not message:
            return Result(content="[SendMessage] message 不能为空", is_error=True)

        new_bg = await self._mgr.send_message(name, message)
        if new_bg is None:
            return Result(
                content=f"[SendMessage] 未找到名为 {name!r} 的存活任务（或已 cancelled）",
                is_error=True,
            )

        return Result(
            content=json.dumps(
                {"task_id": new_bg.id, "name": name, "status": "async_launched"},
                ensure_ascii=False,
            )
        )
