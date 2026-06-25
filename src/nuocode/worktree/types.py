"""worktree 数据结构（chap14 F2-F4）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


@dataclass
class Worktree:
    """单个 Worktree 的元信息（spec F2）。

    - ``name``: 原始 slug（可能含 /）
    - ``path``: 绝对路径
    - ``branch``: ``worktree-<flat_slug>``
    - ``based_on``: 创建时的 base 引用（HEAD 或具体 commit）
    - ``head_commit``: 创建时的 commit SHA
    - ``created``: 创建时间
    - ``manual``: True=用户手动创建（/worktree create 路径），False=自动（SubAgent 临时）
    """

    name: str
    path: str
    branch: str
    based_on: str
    head_commit: str
    created: datetime
    manual: bool


class ExitAction(StrEnum):
    """退出动作枚举。"""

    KEEP = "keep"
    REMOVE = "remove"


@dataclass
class ExitOptions:
    """退出选项。"""

    discard_changes: bool = False


@dataclass
class ExitReport:
    """退出报告。"""

    removed: bool
    path: str
    branch: str


@dataclass
class AutoCleanupReport:
    """自动清理报告。"""

    kept: bool
    path: str = ""
    branch: str = ""


class WorktreeHasChangesError(Exception):
    """Worktree 有未提交修改或本地多于 base 的 commit。"""
