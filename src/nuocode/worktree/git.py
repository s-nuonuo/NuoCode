"""Git 子进程 helper（chap14 F3/F15）。

提供：
- ``_run_git``: 统一 env 注入的 git 子进程调用
- ``_has_worktree_changes``: 检测 Worktree 是否有未提交修改或新增 commit
- ``_resolve_head_sha_from_fs``: 纯文件系统读取 commit SHA（快速恢复路径）
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path


async def _run_git(work_dir: str, *args: str) -> str:
    """在 work_dir 运行 git 命令，返回 stdout 字符串。

    注入环境变量：
    - ``GIT_TERMINAL_PROMPT=0``：禁止交互式 prompt
    - ``GIT_ASKPASS=""``: 禁止弹出密码框

    失败时抛 ``RuntimeError``（含 stderr 内容）。
    """
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""

    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=work_dir,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    stdout = stdout_b.decode("utf-8", errors="replace").rstrip("\n")
    if proc.returncode != 0:
        stderr = stderr_b.decode("utf-8", errors="replace").rstrip("\n")
        raise RuntimeError(stderr or f"git exited with code {proc.returncode}")
    return stdout


async def _has_worktree_changes(wt_path: str, base_commit: str) -> bool:
    """检测 Worktree 是否有未提交修改或本地新增 commit（相对 base_commit）。

    fail-closed：任一 git 命令出错返回 True（宁可保留）。

    检测两件事：
    1. ``git status --porcelain`` 非空 → 有未提交修改
    2. ``git rev-list --count <base_commit>..HEAD`` > 0 → 有新增 commit
    """
    try:
        status = await _run_git(wt_path, "status", "--porcelain")
        if status.strip():
            return True
    except Exception:  # noqa: BLE001
        return True  # fail-closed

    try:
        count_str = await _run_git(
            wt_path, "rev-list", "--count", f"{base_commit}..HEAD"
        )
        if int(count_str.strip() or "0") > 0:
            return True
    except Exception:  # noqa: BLE001
        return True  # fail-closed

    return False


def _resolve_head_sha_from_fs(wt_path: str) -> str | None:
    """纯文件系统读取 Worktree 的 HEAD commit SHA（快速恢复，不调 git）。

    流程：
    1. 读 ``<wt_path>/.git``，取 gitdir 路径
    2. 读 ``<gitdir>/HEAD``
    3. 若 HEAD 是 ``ref: refs/heads/<name>``，先在 gitdir 里找，再通过 commondir 找主仓 refs
    4. 尝试 packed-refs

    任何读取失败返回 None。
    """
    try:
        git_file = Path(wt_path) / ".git"
        if not git_file.exists():
            return None

        if git_file.is_dir():
            # 主仓库情况（.git 是目录）
            gitdir = str(git_file)
            common_gitdir = gitdir
        else:
            # worktree：.git 是文件，内容为 "gitdir: <path>"
            content = git_file.read_text(encoding="utf-8").strip()
            if not content.startswith("gitdir:"):
                return None
            gitdir = content[len("gitdir:"):].strip()
            if not os.path.isabs(gitdir):
                gitdir = str(Path(wt_path) / gitdir)

            # 通过 commondir 找主仓 gitdir（worktree 的 refs 存在主仓里）
            commondir_file = Path(gitdir) / "commondir"
            if commondir_file.exists():
                rel = commondir_file.read_text(encoding="utf-8").strip()
                if os.path.isabs(rel):
                    common_gitdir = rel
                else:
                    common_gitdir = str((Path(gitdir) / rel).resolve())
            else:
                common_gitdir = gitdir

        head_file = Path(gitdir) / "HEAD"
        if not head_file.exists():
            return None
        head_content = head_file.read_text(encoding="utf-8").strip()

        if head_content.startswith("ref:"):
            ref_path = head_content[len("ref:"):].strip()  # refs/heads/branch-name

            # 先在 gitdir 查，再在 common_gitdir 查
            for search_dir in [gitdir, common_gitdir]:
                ref_file = Path(search_dir) / ref_path
                if ref_file.exists():
                    sha = ref_file.read_text(encoding="utf-8").strip()
                    if sha:
                        return sha

            # 尝试 packed-refs（common_gitdir）
            packed_refs = Path(common_gitdir) / "packed-refs"
            if packed_refs.exists():
                for line in packed_refs.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == ref_path:  # noqa: PLR2004
                        return parts[0]
            return None
        else:
            # HEAD 本身是 SHA（detached HEAD）
            return head_content if len(head_content) == 40 else None  # noqa: PLR2004
    except OSError:
        return None
