"""test_worktree_lifecycle.py：enter / exit / remove / auto_cleanup 单测（chap14 T6）。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nuocode.worktree.manager import Manager
from nuocode.worktree.types import ExitAction, ExitOptions, WorktreeHasChangesError


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


# ── enter ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enter_does_not_change_cwd(git_repo: Path) -> None:
    """enter 不改变进程 cwd。"""
    mgr = Manager(str(git_repo))
    await mgr.create("enter-test", "HEAD", manual=True)

    cwd_before = Path.cwd()
    session = await mgr.enter("enter-test")
    cwd_after = Path.cwd()

    assert cwd_before == cwd_after
    assert session.worktree_name == "enter-test"
    assert session.session_id  # 非空


@pytest.mark.asyncio
async def test_enter_session_persisted(git_repo: Path) -> None:
    """enter 后 session 文件被持久化。"""
    mgr = Manager(str(git_repo))
    await mgr.create("persist-test", "HEAD", manual=True)
    await mgr.enter("persist-test")

    assert mgr.session_file.exists()
    content = mgr.session_file.read_text()
    assert "persist-test" in content


@pytest.mark.asyncio
async def test_enter_returns_correct_fields(git_repo: Path) -> None:
    """enter 返回 session 含 original_cwd、worktree_path 等字段。"""
    mgr = Manager(str(git_repo))
    await mgr.create("field-test", "HEAD", manual=True)
    session = await mgr.enter("field-test")

    assert session.original_cwd  # 非空
    assert session.worktree_path  # 非空
    assert session.worktree_name == "field-test"
    assert session.session_id  # 非空


# ── exit ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exit_keep_keeps_worktree(git_repo: Path) -> None:
    """exit KEEP 不删除 Worktree 目录。"""
    mgr = Manager(str(git_repo))
    wt = await mgr.create("exit-keep", "HEAD", manual=True)
    await mgr.enter("exit-keep")
    report = await mgr.exit("exit-keep", ExitAction.KEEP, ExitOptions())

    assert not report.removed
    assert Path(wt.path).exists()


@pytest.mark.asyncio
async def test_exit_remove_clean(git_repo: Path) -> None:
    """exit REMOVE + 无变更 + discard=True → 目录被删除。"""
    mgr = Manager(str(git_repo))
    wt = await mgr.create("exit-remove", "HEAD", manual=True)
    await mgr.enter("exit-remove")
    report = await mgr.exit("exit-remove", ExitAction.REMOVE, ExitOptions(discard_changes=True))

    assert report.removed
    assert not Path(wt.path).exists()


@pytest.mark.asyncio
async def test_exit_remove_with_changes_raises(git_repo: Path) -> None:
    """exit REMOVE 有未提交修改时抛 WorktreeHasChangesError。"""
    mgr = Manager(str(git_repo))
    wt = await mgr.create("exit-dirty", "HEAD", manual=True)
    # 在 worktree 里写文件（未提交）
    (Path(wt.path) / "dirty.txt").write_text("dirty\n")
    await mgr.enter("exit-dirty")

    with pytest.raises(WorktreeHasChangesError):
        await mgr.exit("exit-dirty", ExitAction.REMOVE, ExitOptions())


@pytest.mark.asyncio
async def test_exit_session_cleared(git_repo: Path) -> None:
    """exit 后 current_session() 为 None，session 文件写 null。"""
    mgr = Manager(str(git_repo))
    await mgr.create("session-clear", "HEAD", manual=True)
    await mgr.enter("session-clear")
    await mgr.exit("session-clear", ExitAction.KEEP, ExitOptions())

    assert mgr.current_session() is None


# ── remove ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remove_non_current_session(git_repo: Path) -> None:
    """remove 允许删除非当前 session 的 Worktree。"""
    mgr = Manager(str(git_repo))
    wt = await mgr.create("removable", "HEAD", manual=True)
    await mgr.remove("removable", ExitOptions(discard_changes=True))
    assert not Path(wt.path).exists()
    assert mgr.get("removable") is None


# ── auto_cleanup ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_cleanup_manual_kept(git_repo: Path) -> None:
    """auto_cleanup manual=True 直接返回 kept=True。"""
    mgr = Manager(str(git_repo))
    await mgr.create("manual-wt", "HEAD", manual=True)
    report = await mgr.auto_cleanup("manual-wt")
    assert report.kept is True


@pytest.mark.asyncio
async def test_auto_cleanup_no_changes_removes(git_repo: Path) -> None:
    """auto_cleanup manual=False 且无变更时 remove，返回 kept=False。"""
    mgr = Manager(str(git_repo))
    wt = await mgr.create("temp-wt", "HEAD", manual=False)
    report = await mgr.auto_cleanup("temp-wt")
    assert report.kept is False
    assert not Path(wt.path).exists()


@pytest.mark.asyncio
async def test_auto_cleanup_has_changes_kept(git_repo: Path) -> None:
    """auto_cleanup manual=False 有变更时 kept=True，路径和分支非空。"""
    mgr = Manager(str(git_repo))
    wt = await mgr.create("dirty-temp", "HEAD", manual=False)
    (Path(wt.path) / "new.txt").write_text("modified\n")
    report = await mgr.auto_cleanup("dirty-temp")
    assert report.kept is True
    assert report.path
    assert report.branch
