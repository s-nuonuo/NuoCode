"""Worktree create + 快速恢复 + 创建后设置（chap14 F6-F10/T5）。"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from nuocode.worktree.git import _resolve_head_sha_from_fs, _run_git
from nuocode.worktree.slug import flat_slug, validate_slug
from nuocode.worktree.types import Worktree

if TYPE_CHECKING:
    from nuocode.worktree.manager import Manager


async def _create(manager: Manager, name: str, base_ref: str, manual: bool) -> Worktree:
    """创建 Worktree（spec F6）。"""
    validate_slug(name)

    async with manager.lock:
        if name in manager.active:
            raise ValueError(f"Worktree {name!r} 已存在")

        flat = flat_slug(name)
        wt_path = manager.worktree_dir / flat
        branch_name = f"worktree-{flat}"

        # 快速恢复路径：目录已存在
        if wt_path.exists():
            head_sha = _resolve_head_sha_from_fs(str(wt_path)) or ""
            wt = Worktree(
                name=name,
                path=str(wt_path),
                branch=branch_name,
                based_on=base_ref,
                head_commit=head_sha,
                created=datetime.fromtimestamp(wt_path.stat().st_mtime),
                manual=manual,
            )
            manager.active[name] = wt
            return wt

    # 创建路径（持锁外执行 git，避免长锁）
    try:
        await _run_git(
            manager.repo_root,
            "worktree",
            "add",
            "-B",
            branch_name,
            str(wt_path),
            base_ref,
        )
    except RuntimeError as e:
        shutil.rmtree(wt_path, ignore_errors=True)
        raise RuntimeError(f"git worktree add 失败: {e}") from e

    # 创建后设置（best-effort）
    await _perform_post_creation_setup(manager.repo_root, wt_path, manager.symlink_dirs)

    # 读取 HEAD SHA
    try:
        head_sha = await _run_git(str(wt_path), "rev-parse", "HEAD")
    except RuntimeError:
        head_sha = ""

    wt = Worktree(
        name=name,
        path=str(wt_path),
        branch=branch_name,
        based_on=base_ref,
        head_commit=head_sha,
        created=datetime.now(),
        manual=manual,
    )
    async with manager.lock:
        manager.active[name] = wt
    return wt


async def _perform_post_creation_setup(
    repo_root: str, wt_path: Path, symlink_dirs: list[str]
) -> None:
    """执行创建后四步设置（spec F7-F10），每步失败只警告不中断。"""
    _copy_local_configs(repo_root, wt_path)
    _setup_git_hooks(repo_root, wt_path)
    _symlink_large_dirs(repo_root, wt_path, symlink_dirs)
    await _copy_included_ignored(repo_root, wt_path)


def _copy_local_configs(repo_root: str, wt_path: Path) -> None:
    """设置 A：复制本地配置文件（spec F7）。"""
    config_files = [
        Path(".nuocode") / "config.yaml",
        Path(".nuocode") / "settings.local.yaml",
    ]
    for rel in config_files:
        src = Path(repo_root) / rel
        dst = wt_path / rel
        if not src.exists():
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.copy(src, dst)
        except Exception as e:  # noqa: BLE001
            print(f"worktree: setup copy_configs: {e}", file=sys.stderr)


def _setup_git_hooks(repo_root: str, wt_path: Path) -> None:
    """设置 B：配置 git hooks（spec F8）。"""
    try:
        hooks_path: str | None = None
        # 优先检查 .husky/
        husky_dir = Path(repo_root) / ".husky"
        if husky_dir.exists() and husky_dir.is_dir():
            hooks_path = str(husky_dir)
        else:
            # 读主仓库 core.hooksPath
            result = subprocess.run(
                ["git", "-C", repo_root, "config", "--get", "core.hooksPath"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                h = result.stdout.strip()
                hooks_path = h if os.path.isabs(h) else str(Path(repo_root) / h)

        if hooks_path:
            subprocess.run(
                ["git", "-C", str(wt_path), "config", "core.hooksPath", hooks_path],
                capture_output=True,
                text=True,
                check=True,
            )
    except Exception as e:  # noqa: BLE001
        print(f"worktree: setup git_hooks: {e}", file=sys.stderr)


def _symlink_large_dirs(repo_root: str, wt_path: Path, symlink_dirs: list[str]) -> None:
    """设置 C：软链大目录（spec F9）。"""
    for d in symlink_dirs:
        src = Path(repo_root) / d
        dst = wt_path / d
        if not src.exists():
            continue
        if dst.exists() or dst.is_symlink():
            continue
        try:
            os.symlink(src, dst)
        except Exception as e:  # noqa: BLE001
            print(f"worktree: setup symlink {d}: {e}", file=sys.stderr)


async def _copy_included_ignored(repo_root: str, wt_path: Path) -> None:
    """设置 D：按 .worktreeinclude 复制被忽略但运行需要的文件（spec F10）。"""
    include_file = Path(repo_root) / ".worktreeinclude"
    if not include_file.exists():
        return

    try:
        patterns = [
            line.strip()
            for line in include_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
    except Exception as e:  # noqa: BLE001
        print(f"worktree: setup copy_included_ignored read .worktreeinclude: {e}", file=sys.stderr)
        return

    if not patterns:
        return

    # 列出所有忽略的文件
    try:
        from nuocode.worktree.git import _run_git as run_git
        ignored_output = await run_git(
            repo_root,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
        )
        ignored_files = [f.strip() for f in ignored_output.splitlines() if f.strip()]
    except Exception as e:  # noqa: BLE001
        print(f"worktree: setup copy_included_ignored list ignored: {e}", file=sys.stderr)
        return

    for rel_file in ignored_files:
        matched = any(fnmatch.fnmatch(rel_file, pat) for pat in patterns)
        if not matched:
            continue
        src = Path(repo_root) / rel_file
        dst = wt_path / rel_file
        if not src.exists():
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)
        except Exception as e:  # noqa: BLE001
            print(f"worktree: setup copy {rel_file}: {e}", file=sys.stderr)
