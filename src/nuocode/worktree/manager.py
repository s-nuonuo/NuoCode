"""WorktreeManager 核心类（chap14 F4-F5）。"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from nuocode.worktree.session import WorktreeSession, clear_session, load_session
from nuocode.worktree.types import AutoCleanupReport, ExitAction, ExitOptions, ExitReport, Worktree

if TYPE_CHECKING:
    pass

DEFAULT_SYMLINK_DIRS = ["node_modules", ".venv", "vendor"]


class Manager:
    """Worktree 完整生命周期管理器（spec F4-F5）。

    单一 asyncio.Lock 保护内部 ``active`` 映射。
    Worktree 内部 git 操作不持锁，避免长锁。
    """

    def __init__(self, repo_root: str) -> None:
        self.repo_root: str = str(Path(repo_root).resolve())
        # 校验 repo_root 是 git 仓库根目录
        result = subprocess.run(
            ["git", "-C", self.repo_root, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ValueError(f"非 git 仓库根目录: {repo_root!r}")
        detected_root = result.stdout.strip()
        if Path(detected_root).resolve() != Path(self.repo_root).resolve():
            raise ValueError(
                f"repo_root {repo_root!r} 不是 git 仓库的顶层目录 "
                f"（顶层目录为 {detected_root!r}）"
            )

        self.worktree_dir: Path = Path(self.repo_root) / ".nuocode" / "worktrees"
        self.session_file: Path = Path(self.repo_root) / ".nuocode" / "worktree_session.json"
        self.symlink_dirs: list[str] = list(DEFAULT_SYMLINK_DIRS)
        self.lock: asyncio.Lock = asyncio.Lock()
        self.active: dict[str, Worktree] = {}
        self._current_session: WorktreeSession | None = None

        # 创建 worktree_dir
        self.worktree_dir.mkdir(parents=True, exist_ok=True)

        # 加载 session
        try:
            session = load_session(self.session_file)
        except ValueError as e:
            print(f"worktree: session 文件损坏，已清空: {e}", file=sys.stderr)
            clear_session(self.session_file)
            session = None

        if session is not None:
            if not Path(session.worktree_path).exists():
                print(
                    "worktree: session worktree gone, cleared",
                    file=sys.stderr,
                )
                clear_session(self.session_file)
                session = None
        self._current_session = session

        # 快速恢复：扫描 worktree_dir 子目录还原 active
        self._scan_active()

    def _scan_active(self) -> None:
        """扫描 worktree_dir，按文件系统快速恢复 active 映射。"""
        from nuocode.worktree.git import _resolve_head_sha_from_fs

        for subdir in self.worktree_dir.iterdir():
            if not subdir.is_dir():
                continue
            head_sha = _resolve_head_sha_from_fs(str(subdir)) or ""
            # flat_slug → name：子目录名即 flat_slug
            flat = subdir.name
            # 尝试从 flat 还原 name（简单：直接用 flat 作为 name，
            # 实际 name 含 / 的在真实创建时会写入 metadata；快速恢复时用 flat 代替）
            name = flat  # 快速恢复不保留原始 name，用 flat 代替
            branch = f"worktree-{flat}"
            wt = Worktree(
                name=name,
                path=str(subdir),
                branch=branch,
                based_on="",
                head_commit=head_sha,
                created=datetime.fromtimestamp(subdir.stat().st_mtime),
                manual=True,  # 快速恢复无法判断，保守为 True（不走自动清理）
            )
            self.active[name] = wt

    def list(self) -> list[Worktree]:
        """返回当前所有 Worktree，按 name 排序。"""
        return sorted(self.active.values(), key=lambda w: w.name)

    def get(self, name: str) -> Worktree | None:
        """按 name 获取 Worktree，不存在返回 None。"""
        return self.active.get(name)

    def current_session(self) -> WorktreeSession | None:
        """返回当前活跃的 WorktreeSession，无 session 返回 None。"""
        return self._current_session

    # ── 委托方法（由 create.py / lifecycle.py / sweep.py 填充）──────────────

    async def create(self, name: str, base_ref: str, manual: bool) -> Worktree:
        from nuocode.worktree.create import _create
        return await _create(self, name, base_ref, manual)

    async def enter(self, name: str) -> WorktreeSession:
        from nuocode.worktree.lifecycle import _enter
        return await _enter(self, name)

    async def exit(
        self, name: str, action: ExitAction, opts: ExitOptions
    ) -> ExitReport:
        from nuocode.worktree.lifecycle import _exit
        return await _exit(self, name, action, opts)

    async def remove(self, name: str, opts: ExitOptions) -> None:
        from nuocode.worktree.lifecycle import _remove
        await _remove(self, name, opts)

    async def auto_cleanup(self, name: str) -> AutoCleanupReport:
        from nuocode.worktree.lifecycle import _auto_cleanup
        return await _auto_cleanup(self, name)

    async def sweep_stale(self, cutoff: datetime) -> list[str]:
        from nuocode.worktree.sweep import _sweep_stale
        return await _sweep_stale(self, cutoff)
