"""in-process 后端实现（chap15 F18-F19）。

复用 task.Manager.launch 在 asyncio task 里跑 run_to_completion。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nuocode.team.types import BackendType

if TYPE_CHECKING:
    from nuocode.task.manager import Manager as TaskManager
    from nuocode.team.backend import SpawnRequest


class InProcessBackend:
    """in-process 执行后端（F18）。

    在事件循环里起一个 asyncio task 跑 run_to_completion。
    wake 为 no-op，kill 通过 task.Manager.stop 实现。
    """

    def __init__(self, task_mgr: TaskManager) -> None:
        self._task_mgr = task_mgr

    def type(self) -> BackendType:
        return BackendType.IN_PROCESS

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        """启动 in-process 子 Agent（F18）。

        从 req.sub_agent / req.conv 取已构造好的对象。
        返回 ("", task_id)，pane_id 为空。
        """
        if req.sub_agent is None or req.conv is None:
            raise ValueError("in-process spawn 需要 req.sub_agent 和 req.conv")

        task_id = await self._task_mgr.launch(
            sub_agent=req.sub_agent,
            conv=req.conv,
            task=req.initial_prompt,
            name=req.member_name,
        )
        # 修正 agent_id：用 task_id 作为 agent_id
        return "", task_id

    async def wake(self, pane_id: str, agent_id: str) -> None:  # noqa: ARG002
        """no-op，同进程下一轮 Loop 自动读邮箱（F18）。"""

    async def kill(self, pane_id: str, agent_id: str) -> None:  # noqa: ARG002
        """取消 asyncio task（F18）。"""
        if agent_id:
            self._task_mgr.stop(agent_id)
