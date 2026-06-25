"""test_worktree_git.py：_run_git / _has_worktree_changes / _resolve_head_sha_from_fs 单测（chap14 T3）。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nuocode.worktree.git import (
    _has_worktree_changes,
    _resolve_head_sha_from_fs,
    _run_git,
)


# ── fixture：临时 git 仓库 ──────────────────────────────────────────────────

@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """创建一个有初始 commit 的临时 git 仓库。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "hello.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


@pytest.fixture
def git_worktree(git_repo: Path, tmp_path: Path) -> tuple[Path, Path]:
    """在 git_repo 基础上创建一个 worktree，返回 (repo, worktree_path)。"""
    wt = tmp_path / "worktree"
    subprocess.run(
        ["git", "worktree", "add", "-B", "wt-branch", str(wt), "HEAD"],
        cwd=git_repo, check=True, capture_output=True,
    )
    return git_repo, wt


# ── _run_git ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_git_success(git_repo: Path) -> None:
    """_run_git 返回 stdout 并去掉尾部换行。"""
    result = await _run_git(str(git_repo), "rev-parse", "--abbrev-ref", "HEAD")
    assert result == "main"


@pytest.mark.asyncio
async def test_run_git_failure(git_repo: Path) -> None:
    """_run_git 失败时抛 RuntimeError。"""
    with pytest.raises(RuntimeError):
        await _run_git(str(git_repo), "nonexistent-command-xyz")


@pytest.mark.asyncio
async def test_run_git_env_injected(git_repo: Path, monkeypatch) -> None:
    """_run_git 在正常调用时不依赖 GIT_TERMINAL_PROMPT（只验证不崩溃）。"""
    monkeypatch.delenv("GIT_TERMINAL_PROMPT", raising=False)
    result = await _run_git(str(git_repo), "status", "--porcelain")
    assert isinstance(result, str)


# ── _has_worktree_changes ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_has_worktree_changes_clean(git_worktree: tuple[Path, Path]) -> None:
    """无修改时返回 False。"""
    _, wt = git_worktree
    # 获取 HEAD commit
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=wt, capture_output=True, text=True
    )
    head = result.stdout.strip()
    assert not await _has_worktree_changes(str(wt), head)


@pytest.mark.asyncio
async def test_has_worktree_changes_dirty(git_worktree: tuple[Path, Path]) -> None:
    """有未提交修改时返回 True。"""
    _, wt = git_worktree
    (wt / "new_file.txt").write_text("dirty\n")
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=wt, capture_output=True, text=True
    )
    head = result.stdout.strip()
    assert await _has_worktree_changes(str(wt), head)


@pytest.mark.asyncio
async def test_has_worktree_changes_new_commit(git_worktree: tuple[Path, Path]) -> None:
    """有新增 commit（相对 base_commit）时返回 True。"""
    _, wt = git_worktree
    base_result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=wt, capture_output=True, text=True
    )
    base_commit = base_result.stdout.strip()

    # 在 worktree 中新增 commit
    (wt / "new.txt").write_text("new\n")
    subprocess.run(["git", "add", "."], cwd=wt, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "new commit"], cwd=wt, capture_output=True, check=True)

    assert await _has_worktree_changes(str(wt), base_commit)


@pytest.mark.asyncio
async def test_has_worktree_changes_bad_dir() -> None:
    """git 命令出错时 fail-closed 返回 True。"""
    assert await _has_worktree_changes("/nonexistent/path", "HEAD")


# ── _resolve_head_sha_from_fs ─────────────────────────────────────────────

def test_resolve_head_sha_from_fs_worktree(git_worktree: tuple[Path, Path]) -> None:
    """在真实 worktree 路径下返回 commit SHA（40 位 hex）。"""
    _, wt = git_worktree
    sha = _resolve_head_sha_from_fs(str(wt))
    assert sha is not None
    assert len(sha) == 40  # noqa: PLR2004
    assert all(c in "0123456789abcdef" for c in sha)


def test_resolve_head_sha_from_fs_main_repo(git_repo: Path) -> None:
    """主仓库路径下（.git 是目录）也能解析 SHA。"""
    sha = _resolve_head_sha_from_fs(str(git_repo))
    assert sha is not None
    assert len(sha) == 40  # noqa: PLR2004


def test_resolve_head_sha_from_fs_nonexistent() -> None:
    """不存在的路径返回 None。"""
    assert _resolve_head_sha_from_fs("/nonexistent/xyz") is None
