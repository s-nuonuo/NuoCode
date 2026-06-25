"""worktree_adapter.py：TUI 侧 WorktreeAccessor 实现（chap14 F30/T14）。

把 Manager 操作适配给 command.ui.WorktreeAccessor 协议，
同时在 enter/exit 时更新 NuoCodeApp.active_cwd。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nuocode.tui.app import NuoCodeApp
    from nuocode.worktree.manager import Manager


class WorktreeAccessorImpl:
    """WorktreeAccessor 协议实现。"""

    def __init__(self, mgr: Manager, app: NuoCodeApp) -> None:
        self._mgr = mgr
        self._app = app

    async def create(self, name: str) -> tuple[str, str]:
        wt = await self._mgr.create(name, "HEAD", manual=True)
        return wt.path, wt.branch

    def list(self):  # -> list[WorktreeSummary]
        from nuocode.command.ui import WorktreeSummary
        items = []
        current_session = self._mgr.current_session()
        current_name = current_session.worktree_name if current_session else None
        for wt in self._mgr.list():
            items.append(WorktreeSummary(
                name=wt.name,
                path=wt.path,
                branch=wt.branch,
                active=(wt.name == current_name),
                manual=wt.manual,
            ))
        return items

    async def enter(self, name: str) -> None:
        wt = await self._mgr.enter(name)
        self._app.active_cwd = wt.worktree_path

    async def exit(self, action: str, discard: bool) -> bool:
        """退出当前 Worktree。返回 True 表示已 remove。"""
        from nuocode.worktree.types import ExitAction, ExitOptions
        opts = ExitOptions(force=discard)
        report = await self._mgr.exit(action=ExitAction(action), opts=opts)
        # 退出后 active_cwd 恢复 repo_root（主 worktree）
        self._app.active_cwd = self._mgr.repo_root
        return report.removed

    async def remove(self, name: str, discard: bool) -> None:
        from nuocode.worktree.types import ExitOptions
        opts = ExitOptions(force=discard)
        await self._mgr.remove(name, opts)
