"""Worktree 生命周期：enter / exit / remove / auto_cleanup（chap14 F11-F14/T6）。"""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

from nuocode.worktree.git import _has_worktree_changes, _run_git
from nuocode.worktree.session import WorktreeSession, save_session
from nuocode.worktree.types import (
    AutoCleanupReport,
    ExitAction,
    ExitOptions,
    ExitReport,
    WorktreeHasChangesError,
)

if TYPE_CHECKING:
    from nuocode.worktree.manager import Manager


async def _enter(manager: Manager, name: str) -> WorktreeSession:
    """进入 Worktree，构造 WorktreeSession，不调 os.chdir（spec F11）。"""
    async with manager.lock:
        wt = manager.active.get(name)
        if wt is None:
            raise ValueError(f"Worktree {name!r} 不存在")

        original_cwd = str(Path.cwd())

        # 读取当前 branch 与 HEAD（失败用空字符串兜底）
        original_branch = ""
        original_head = ""
        try:
            original_branch = await _run_git(
                manager.repo_root, "rev-parse", "--abbrev-ref", "HEAD"
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            original_head = await _run_git(manager.repo_root, "rev-parse", "HEAD")
        except Exception:  # noqa: BLE001
            pass

        session_id = secrets.token_hex(8)
        session = WorktreeSession(
            original_cwd=original_cwd,
            worktree_path=wt.path,
            worktree_name=name,
            original_branch=original_branch,
            original_head_commit=original_head,
            session_id=session_id,
        )
        manager._current_session = session
        save_session(manager.session_file, session)
        return session


async def _exit(
    manager: Manager, name: str, action: ExitAction, opts: ExitOptions
) -> ExitReport:
    """退出 Worktree，可选删除（spec F12）。"""
    async with manager.lock:
        session = manager._current_session
        if session is None:
            raise ValueError("当前无活跃 Worktree session")
        if session.worktree_name != name:
            raise ValueError(
                f"只能退出当前 session 的 Worktree {session.worktree_name!r}，"
                f"不能退出 {name!r}"
            )

        wt = manager.active.get(name)
        if wt is None:
            raise ValueError(f"Worktree {name!r} 不在 active 映射中")

        if action == ExitAction.REMOVE and not opts.discard_changes:
            has_changes = await _has_worktree_changes(wt.path, wt.head_commit)
            if has_changes:
                raise WorktreeHasChangesError(
                    f"Worktree {name!r} 有未提交修改或新增 commit，"
                    "请先提交或使用 --discard 跳过保护"
                )

        # 兜底切回原 cwd
        with contextlib.suppress(OSError):
            os.chdir(session.original_cwd)

        manager._current_session = None
        save_session(manager.session_file, None)

        removed = False
        if action == ExitAction.REMOVE:
            await _do_remove_worktree(manager, name, wt.path, wt.branch)
            removed = True

        return ExitReport(removed=removed, path=wt.path, branch=wt.branch)


async def _remove(manager: Manager, name: str, opts: ExitOptions) -> None:
    """独立 remove 入口，允许删除非当前 session 的 Worktree（spec F13）。"""
    async with manager.lock:
        wt = manager.active.get(name)
        if wt is None:
            raise ValueError(f"Worktree {name!r} 不存在")

        if not opts.discard_changes:
            has_changes = await _has_worktree_changes(wt.path, wt.head_commit)
            if has_changes:
                raise WorktreeHasChangesError(
                    f"Worktree {name!r} 有未提交修改或新增 commit，"
                    "使用 --discard 跳过保护"
                )

        await _do_remove_worktree(manager, name, wt.path, wt.branch)


async def _do_remove_worktree(
    manager: Manager, name: str, wt_path: str, branch: str
) -> None:
    """实际执行 worktree remove + branch -D（不持锁调用）。"""
    try:
        await _run_git(manager.repo_root, "worktree", "remove", "--force", wt_path)
    except Exception as e:  # noqa: BLE001
        import sys
        print(f"worktree: remove {wt_path!r}: {e}", file=sys.stderr)

    await asyncio.sleep(0.1)  # 等待 git lockfile 竞态

    try:
        await _run_git(manager.repo_root, "branch", "-D", branch)
    except Exception as e:  # noqa: BLE001
        import sys
        print(f"worktree: delete branch {branch!r}: {e}", file=sys.stderr)

    manager.active.pop(name, None)


async def _auto_cleanup(manager: Manager, name: str) -> AutoCleanupReport:
    """SubAgent 退出时自动清理（spec F14）。

    - manual=True → 直接 kept
    - 无变更 → remove
    - 有变更 → kept（返回路径供主 Agent review）
    """
    wt = manager.active.get(name)
    if wt is None:
        raise ValueError(f"Worktree {name!r} 不存在")

    if wt.manual:
        return AutoCleanupReport(kept=True, path=wt.path, branch=wt.branch)

    has_changes = await _has_worktree_changes(wt.path, wt.head_commit)
    if not has_changes:
        await manager.remove(name, ExitOptions(discard_changes=True))
        return AutoCleanupReport(kept=False)
    else:
        return AutoCleanupReport(kept=True, path=wt.path, branch=wt.branch)
