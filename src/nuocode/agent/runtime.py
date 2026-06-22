"""跨 Agent.run 边界的会话级运行时容器。

包含 compact 子系统所需的全部长生命周期状态：
- ContentReplacementState：第 1 层决策账本
- AutoCompactTrackingState：自动摘要熔断状态
- RecoveryState：最近读过的文件追踪
- SessionContext：本次进程的会话身份与落盘目录
- usage_anchor / anchor_msg_len：估算锚点

由 ``cli.py`` 在启动时创建；TUI 持有引用并在每次 ``Agent.run`` 之间复用。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nuocode.compact import (
    AutoCompactTrackingState,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
)
from nuocode.skills import ActiveSkills

if TYPE_CHECKING:
    from nuocode.hook.engine import Engine


@dataclass
class SessionRuntime:
    session: SessionContext
    replacement: ContentReplacementState = field(default_factory=ContentReplacementState)
    recovery: RecoveryState = field(default_factory=RecoveryState)
    auto_tracking: AutoCompactTrackingState = field(default_factory=AutoCompactTrackingState)

    # ── 估算锚点 ──
    usage_anchor: int = 0
    """上一次主对话路径流尾真实 usage 之和（input+output+cache_read+cache_write）。"""

    anchor_msg_len: int = 0
    """anchor 被记录时 ``Conversation.length()`` 的快照，用于"只对增量做字符估算"。"""

    # ── 互斥锁：run vs run_force_compact ──
    run_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ── chap11: 跨轮已激活 Skill ──
    active_skills: ActiveSkills = field(default_factory=ActiveSkills)

    # ── chap12: Hook 引擎（可选）与 reminder 队列 ──
    hook_engine: "Engine | None" = field(default=None)
    """当前会话的 Hook 引擎，由 cli.py 注入。"""

    pending_reminders: list[str] = field(default_factory=list)
    """下一轮 LLM 请求前要追加到 reminder 串的文本列表（Hook prompt 动作 / SessionStart 注入）。"""

    _reminders_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def reset_for_new_session(self, ses_ctx: SessionContext) -> None:
        """/clear 入口：原子重置 compact 子状态、回合计数、估算锚点，并替换 session。

        ``run_lock`` 不重置。Hook only_once 集合也在此处清空（通过 hook_engine）。
        """
        self.session = ses_ctx
        self.replacement = ContentReplacementState()
        self.recovery = RecoveryState()
        self.auto_tracking = AutoCompactTrackingState()
        self.usage_anchor = 0
        self.anchor_msg_len = 0
        self.active_skills.clear()
        async with self._reminders_lock:
            self.pending_reminders.clear()
        if self.hook_engine is not None:
            await self.hook_engine.reset_for_new_session()

    def append_reminders(self, prompts: list[str]) -> None:
        """追加 Hook prompt 注入文本（调用方持有 event loop，同步追加即可）。"""
        self.pending_reminders.extend(prompts)

    def take_reminders(self) -> list[str]:
        """取出并清空 pending_reminders，返回副本。"""
        items = list(self.pending_reminders)
        self.pending_reminders.clear()
        return items


__all__ = ["SessionRuntime"]
