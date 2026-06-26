"""后端 Protocol、SpawnRequest 与工厂函数（chap15 F12-F13、T10）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from nuocode.team.types import BackendType

if TYPE_CHECKING:
    pass


# ── SpawnRequest ──────────────────────────────────────────────────────────────

@dataclass
class SpawnRequest:
    """spawn 请求（F13）。

    Pane 后端：initial_prompt 预写入 mailbox，子进程不走命令行。
    in-process 后端：sub_agent/conv/task_mgr 字段必填。
    """

    team_name: str
    member_name: str
    agent_id: str
    worktree_path: str
    session_dir: str
    agent_type: str
    model: str
    initial_prompt: str
    plan_mode_required: bool = False

    # in-process 专用——同进程后端直接复用这三个对象
    sub_agent: Any = None       # agent.Agent
    conv: Any = None            # conversation.Conversation
    task_mgr: Any = None        # task.Manager


# ── Backend Protocol ──────────────────────────────────────────────────────────

class Backend(Protocol):
    """执行后端协议（F12）。"""

    def type(self) -> BackendType: ...

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        """启动队员，返回 (pane_id, agent_id)。"""
        ...

    async def wake(self, pane_id: str, agent_id: str) -> None:
        """唤醒目标 pane（Pane 后端）或 no-op（in-process）。"""
        ...

    async def kill(self, pane_id: str, agent_id: str) -> None:
        """终止 pane（Pane 后端）或 cancel task（in-process）。"""
        ...


# ── 工厂函数 ──────────────────────────────────────────────────────────────────

def new_backend(backend_type: BackendType | str, **deps: Any) -> Backend:
    """按类型创建 Backend 实例（T10）。

    deps 可传：task_mgr（in-process 使用）。
    """
    bt = BackendType(str(backend_type)) if not isinstance(backend_type, BackendType) else backend_type

    if bt == BackendType.TMUX:
        from nuocode.team.backend.tmux import TmuxBackend
        return TmuxBackend()  # type: ignore[return-value]

    if bt == BackendType.ITERM2:
        from nuocode.team.backend.iterm2 import Iterm2Backend
        return Iterm2Backend()  # type: ignore[return-value]

    # in-process
    from nuocode.team.backend.inprocess import InProcessBackend
    task_mgr = deps.get("task_mgr")
    if task_mgr is None:
        raise ValueError("in-process 后端需要 task_mgr")
    return InProcessBackend(task_mgr=task_mgr)  # type: ignore[return-value]
