"""nuocode.worktree 子包公开导出（chap14）。

主要导出：
- ``Manager``: Worktree 完整生命周期管理器
- ``validate_slug``: slug 校验
- ``flat_slug``: slug 扁平化
- ``random_agent_name``: 生成临时 SubAgent Worktree 名
- 数据类型：Worktree / WorktreeSession / ExitAction / ExitOptions / ExitReport / AutoCleanupReport
- 错误类：WorktreeHasChangesError
"""

from nuocode.worktree.manager import Manager
from nuocode.worktree.session import WorktreeSession, clear_session, load_session, save_session
from nuocode.worktree.slug import flat_slug, validate_slug
from nuocode.worktree.sweep import random_agent_name
from nuocode.worktree.types import (
    AutoCleanupReport,
    ExitAction,
    ExitOptions,
    ExitReport,
    Worktree,
    WorktreeHasChangesError,
)

__all__ = [
    "Manager",
    "WorktreeSession",
    "clear_session",
    "load_session",
    "save_session",
    "flat_slug",
    "validate_slug",
    "random_agent_name",
    "AutoCleanupReport",
    "ExitAction",
    "ExitOptions",
    "ExitReport",
    "Worktree",
    "WorktreeHasChangesError",
]
