"""test_worktree_sweep.py：sweep_stale + random_agent_name 单测（chap14 T7）。"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nuocode.worktree.manager import Manager
from nuocode.worktree.sweep import EPHEMERAL_PATTERN, random_agent_name


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


# ── random_agent_name ─────────────────────────────────────────────────────

def test_random_agent_name_pattern() -> None:
    """random_agent_name 返回匹配 agent-a[0-9a-f]{7} 的字符串。"""
    name = random_agent_name()
    assert EPHEMERAL_PATTERN.match(name), f"不匹配 pattern: {name!r}"


def test_random_agent_name_uniqueness() -> None:
    """多次调用结果不同（高概率）。"""
    names = {random_agent_name() for _ in range(10)}
    assert len(names) > 1


def test_ephemeral_pattern() -> None:
    """EPHEMERAL_PATTERN 正则匹配正确。"""
    assert EPHEMERAL_PATTERN.match("agent-a1234567")
    assert EPHEMERAL_PATTERN.match("agent-aabcdef0")
    assert not EPHEMERAL_PATTERN.match("agent-a123456")    # 6 位
    assert not EPHEMERAL_PATTERN.match("agent-a12345678")  # 8 位
    assert not EPHEMERAL_PATTERN.match("agent-b1234567")   # 不是 a
    assert not EPHEMERAL_PATTERN.match("manual-name")


# ── sweep_stale ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_stale_removes_ephemeral_old(git_repo: Path) -> None:
    """匹配模式 + 无变更 + 超时 → 被删除。"""
    mgr = Manager(str(git_repo))
    name = random_agent_name()
    wt = await mgr.create(name, "HEAD", manual=False)

    # 设置为超时（cutoff = now + 1 天，即所有 mtime 都早于 cutoff）
    cutoff = datetime.now() + timedelta(days=1)
    removed = await mgr.sweep_stale(cutoff)

    assert name in removed
    assert not Path(wt.path).exists()


@pytest.mark.asyncio
async def test_sweep_stale_skips_non_matching(git_repo: Path) -> None:
    """不匹配 EPHEMERAL_PATTERN 的 Worktree 不被删除。"""
    mgr = Manager(str(git_repo))
    wt = await mgr.create("manual-wt-keep", "HEAD", manual=True)

    cutoff = datetime.now() + timedelta(days=1)
    removed = await mgr.sweep_stale(cutoff)

    assert "manual-wt-keep" not in removed
    assert Path(wt.path).exists()


@pytest.mark.asyncio
async def test_sweep_stale_skips_dirty(git_repo: Path) -> None:
    """有未提交修改的临时 Worktree 不被删除（fail-closed）。"""
    mgr = Manager(str(git_repo))
    name = random_agent_name()
    wt = await mgr.create(name, "HEAD", manual=False)

    # 在 worktree 里写文件（未提交）
    (Path(wt.path) / "dirty.txt").write_text("dirty\n")

    cutoff = datetime.now() + timedelta(days=1)
    removed = await mgr.sweep_stale(cutoff)

    assert name not in removed
    assert Path(wt.path).exists()


@pytest.mark.asyncio
async def test_sweep_stale_skips_not_old_enough(git_repo: Path) -> None:
    """mtime > cutoff（还未超时）的 Worktree 不被删除。"""
    mgr = Manager(str(git_repo))
    name = random_agent_name()
    await mgr.create(name, "HEAD", manual=False)

    # cutoff 设置为过去时间（所有目录 mtime 都比 cutoff 新）
    cutoff = datetime(2000, 1, 1)
    removed = await mgr.sweep_stale(cutoff)

    assert name not in removed
