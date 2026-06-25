"""后台任务管理器（chap13 F14-F19）。

``Manager`` 持有 ``dict[str, BackgroundTask]``，提供：
- ``launch``：异步启动子 Agent，返回 task_id
- ``get``：按 id 查询
- ``list``：列出所有非终态任务
- ``stop``：发信号取消
- ``adopt_running``：接管正在前台跑的子 Agent 切后台
- ``subscribe_done``：返回一个队列，Manager 在任务完成时推 task_id

生命周期：
  running → completed / failed / cancelled
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# 任务状态常量
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    """后台任务状态容器（chap13 F15）。"""

    id: str
    name: str | None
    sub_agent: Any                # nuocode.agent.Agent
    conv: Any                     # nuocode.conversation.Conversation
    task: str                     # 初始任务文本
    status: str = STATUS_RUNNING
    result: str = ""
    err: BaseException | None = None
    start_time: float = field(default_factory=time.monotonic)
    end_time: float | None = None
    asyncio_task: asyncio.Task | None = field(default=None, repr=False)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    # 简单计数（未来可精细化）
    tool_count: int = 0
    last_activity: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED)

    @property
    def elapsed(self) -> float:
        end = self.end_time or time.monotonic()
        return end - self.start_time


class Manager:
    """后台任务管理器（chap13 F14）。

    单例（由 TUI/CLI 持有），在 asyncio event loop 下使用。
    """

    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._by_name: dict[str, str] = {}       # name → task_id（弱引用）
        self._done_queues: list[asyncio.Queue[str]] = []

    # ── 主要接口 ──────────────────────────────────────────────────────────────

    async def launch(
        self,
        sub_agent: Any,
        conv: Any,
        task: str,
        name: str | None = None,
    ) -> str:
        """异步启动子 Agent，立即返回 task_id（chap13 F16）。

        内部 ``asyncio.create_task`` 驱动执行，完成后推到 done 队列。
        """
        task_id = _new_id()
        bg = BackgroundTask(
            id=task_id,
            name=name,
            sub_agent=sub_agent,
            conv=conv,
            task=task,
        )
        self._tasks[task_id] = bg
        if name:
            self._by_name[name] = task_id

        bg.asyncio_task = asyncio.create_task(
            self._run_bg(bg), name=f"bg-task-{task_id}"
        )
        return task_id

    def get(self, task_id: str) -> BackgroundTask | None:
        """按 id 获取任务（chap13 F20: TaskGet）。"""
        return self._tasks.get(task_id)

    def list(self, *, include_terminal: bool = False) -> list[BackgroundTask]:
        """列出任务，默认只返回非终态（chap13 F20: TaskList）。"""
        tasks = list(self._tasks.values())
        if not include_terminal:
            tasks = [t for t in tasks if not t.is_terminal]
        return tasks

    def stop(self, task_id: str) -> bool:
        """发取消信号；返回是否找到任务（chap13 F20: TaskStop）。"""
        bg = self._tasks.get(task_id)
        if bg is None:
            return False
        bg.cancel_event.set()
        if bg.asyncio_task is not None and not bg.asyncio_task.done():
            bg.asyncio_task.cancel()
        return True

    def find_by_name(self, name: str) -> BackgroundTask | None:
        """按 name 查任务（用于 SendMessage）。"""
        task_id = self._by_name.get(name)
        if task_id is None:
            return None
        return self._tasks.get(task_id)

    def subscribe_done(self) -> asyncio.Queue[str]:
        """返回一个队列，Manager 在任务完成时会 push task_id。

        TUI 通过此队列消费后注入 ``<task-notification>``（F19）。
        """
        q: asyncio.Queue[str] = asyncio.Queue()
        self._done_queues.append(q)
        return q

    async def adopt_running(
        self,
        sub_agent: Any,
        conv: Any,
        task: str,
        name: str | None = None,
        partial_result: str = "",
    ) -> str:
        """接管前台子 Agent 切后台（chap13 F17：超时自动/ESC 手动）。

        与 ``launch`` 的区别：
        - sub_agent/conv 已经持有了部分执行状态
        - partial_result 是已有的部分输出
        """
        task_id = _new_id()
        bg = BackgroundTask(
            id=task_id,
            name=name,
            sub_agent=sub_agent,
            conv=conv,
            task=task,
            result=partial_result,
        )
        self._tasks[task_id] = bg
        if name:
            self._by_name[name] = task_id
        bg.asyncio_task = asyncio.create_task(
            self._run_bg(bg), name=f"bg-task-adopted-{task_id}"
        )
        return task_id

    # ── SendMessage ───────────────────────────────────────────────────────────

    async def send_message(self, name: str, message: str) -> BackgroundTask | None:
        """向存活（completed）后台 Agent 续派任务（F20: SendMessage）。

        找到 name 对应的 BackgroundTask（status=completed），
        把 message 追加为 user 消息后重新 launch 一轮跑动。
        返回新的 BackgroundTask，找不到/已 cancelled 则返回 None。
        """
        bg = self.find_by_name(name)
        if bg is None or bg.status not in (STATUS_COMPLETED,):
            return None

        # 追加消息（不构造新 conv，复用原 conv）
        bg.conv.add_user(message)

        # 重新 launch（复用同一 agent / conv）
        new_id = _new_id()
        new_bg = BackgroundTask(
            id=new_id,
            name=name,
            sub_agent=bg.sub_agent,
            conv=bg.conv,
            task=message,
        )
        self._tasks[new_id] = new_bg
        # 更新 name 弱引用
        self._by_name[name] = new_id

        new_bg.asyncio_task = asyncio.create_task(
            self._run_bg(new_bg), name=f"bg-task-send-{new_id}"
        )
        return new_bg

    # ── 内部 ──────────────────────────────────────────────────────────────────

    async def _run_bg(self, bg: BackgroundTask) -> None:
        """实际驱动子 Agent 跑到底（chap13 F16/N3）。

        任何异常都被捕获，转 status=failed。
        """
        from nuocode.agent import MaxTurnsReached

        try:
            # task 文本已在 conv 中或通过 launch 传入；
            # run_to_completion 若 task 非空会追加 user 消息
            # 这里直接传 "" 避免重复追加（conv 已含任务消息）
            final = await bg.sub_agent.run_to_completion(bg.conv, bg.task)
            bg.result = final
            bg.status = STATUS_COMPLETED
        except asyncio.CancelledError:
            bg.status = STATUS_CANCELLED
            bg.err = None
        except MaxTurnsReached as e:
            bg.result = e.final_text
            bg.status = STATUS_COMPLETED  # 有结果，视为 completed
        except BaseException as e:  # noqa: BLE001
            bg.status = STATUS_FAILED
            bg.err = e
            bg.result = f"[failed] {type(e).__name__}: {e}"
        finally:
            bg.end_time = time.monotonic()
            await self._notify_done(bg.id)

    async def _notify_done(self, task_id: str) -> None:
        """向所有 subscriber 推送 task_id。"""
        dead: list[asyncio.Queue] = []
        for q in self._done_queues:
            try:
                q.put_nowait(task_id)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            # 队列满了说明消费者太慢；从列表移除，防止内存泄漏
            try:
                self._done_queues.remove(q)
            except ValueError:
                pass


def _new_id() -> str:
    return uuid.uuid4().hex[:12]
