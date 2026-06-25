"""sweep_stale：后台过期 Worktree 清理（chap14 F33-F34/T7）。"""

from __future__ import annotations

import re
import secrets
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from nuocode.worktree.git import _run_git
from nuocode.worktree.types import ExitOptions

if TYPE_CHECKING:
    from nuocode.worktree.manager import Manager

# 第一层：临时 SubAgent Worktree 命名模式
EPHEMERAL_PATTERN = re.compile(r"^agent-a[0-9a-f]{7}$")


def random_agent_name() -> str:
    """生成临时 SubAgent Worktree 名（spec F34 / G3）。

    格式：``agent-a<7位 hex>``，匹配 EPHEMERAL_PATTERN。
    """
    return "agent-a" + secrets.token_hex(4)[:7]


async def _sweep_stale(manager: Manager, cutoff: datetime) -> list[str]:
    """后台清理过期临时 Worktree（spec F33）。

    三层过滤：
    1. 名字匹配 EPHEMERAL_PATTERN
    2. 目录 mtime > cutoff（未超时）跳过；当前 session 目录跳过
    3. 有未提交修改 / 未推送 commit（fail-closed）跳过

    通过三层的目录调用 remove 并记入返回列表。
    """
    removed: list[str] = []
    current_session = manager.current_session()

    for subdir in Path(manager.worktree_dir).iterdir():
        if not subdir.is_dir():
            continue

        # 第一层：名字匹配
        if not EPHEMERAL_PATTERN.match(subdir.name):
            continue

        # 第二层：时间过滤
        try:
            mtime = datetime.fromtimestamp(subdir.stat().st_mtime)
        except OSError:
            continue
        if mtime > cutoff:
            continue  # 未超时，跳过

        # 第二层：当前 session 跳过
        if (
            current_session is not None
            and Path(current_session.worktree_path).resolve() == subdir.resolve()
        ):
            continue

        # 第三层：变更检查（fail-closed）
        name = subdir.name
        # 找 active 中对应的 Worktree（快速恢复后 name == flat）
        wt = manager.active.get(name)
        # head_commit 空时用 HEAD（快速恢复未能读取时的兜底）
        head_commit = (wt.head_commit if wt and wt.head_commit else "") or ""
        # 如果没有 base commit，用 HEAD^ 表示"当前 commit 之前"（即无新增 commit）
        # 实际上：直接检测 status --porcelain 即可，rev-list 的 base 用 HEAD 会得到 0
        if not head_commit:
            head_commit = "HEAD"

        try:
            # 未提交修改
            status = await _run_git(str(subdir), "status", "--porcelain")
            if status.strip():
                continue  # 有变更，跳过
        except Exception:  # noqa: BLE001
            continue  # fail-closed

        try:
            # 检查是否有 remote（无 remote 时跳过未推送检查）
            remotes = await _run_git(str(subdir), "remote")
            if remotes.strip():
                # 有 remote，检查未推送 commit
                unpushed = await _run_git(
                    str(subdir),
                    "rev-list",
                    "--max-count=1",
                    "HEAD",
                    "--not",
                    "--remotes",
                )
                if unpushed.strip():
                    continue  # 有未推送 commit，跳过
        except Exception:  # noqa: BLE001
            continue  # fail-closed

        # 通过三层过滤，执行 remove
        try:
            await manager.remove(name, ExitOptions(discard_changes=True))
            removed.append(name)
        except Exception as e:  # noqa: BLE001
            print(f"worktree: sweep_stale remove {name!r}: {e}", file=sys.stderr)

    return removed
