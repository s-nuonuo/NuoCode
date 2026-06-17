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

from nuocode.compact import (
    AutoCompactTrackingState,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
)


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


__all__ = ["SessionRuntime"]
