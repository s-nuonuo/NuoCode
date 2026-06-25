"""test_worktree_create.py：create + 创建后设置单测（chap14 T5）。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nuocode.worktree.manager import Manager


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


# ── create 主流程 ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_basic(git_repo: Path) -> None:
    """create 成功后 Worktree 目录存在，分支为 worktree-alice。"""
    mgr = Manager(str(git_repo))
    wt = await mgr.create("alice", "HEAD", manual=True)

    assert wt.name == "alice"
    assert wt.branch == "worktree-alice"
    assert Path(wt.path).exists()
    assert wt.head_commit  # 非空

    # active 映射有了
    assert mgr.get("alice") is not None


@pytest.mark.asyncio
async def test_create_nested_slug(git_repo: Path) -> None:
    """create team/alice 落地 worktrees/team+alice/，分支 worktree-team+alice。"""
    mgr = Manager(str(git_repo))
    wt = await mgr.create("team/alice", "HEAD", manual=True)

    assert wt.branch == "worktree-team+alice"
    assert Path(wt.path).name == "team+alice"
    assert Path(wt.path).exists()


@pytest.mark.asyncio
async def test_create_duplicate_raises(git_repo: Path) -> None:
    """对已存在的 name 再次 create 抛异常。"""
    mgr = Manager(str(git_repo))
    await mgr.create("dup", "HEAD", manual=True)
    with pytest.raises(ValueError, match="已存在"):
        await mgr.create("dup", "HEAD", manual=True)


@pytest.mark.asyncio
async def test_create_invalid_slug(git_repo: Path) -> None:
    """slug 不合法时抛 ValueError。"""
    mgr = Manager(str(git_repo))
    with pytest.raises(ValueError):
        await mgr.create("../etc", "HEAD", manual=True)


# ── 快速恢复路径 ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_fast_restore(git_repo: Path) -> None:
    """目录已存在时走快速恢复，不调 git worktree add。"""
    mgr = Manager(str(git_repo))
    # 先正常创建
    await mgr.create("restore-test", "HEAD", manual=True)
    # 从 active 中删掉，模拟重启
    del mgr.active["restore-test"]

    # 用 patch 监控 _run_git 是否被调用
    run_git_calls: list = []
    original_run_git = __import__("nuocode.worktree.git", fromlist=["_run_git"])._run_git

    async def spy_run_git(work_dir: str, *args: str) -> str:
        run_git_calls.append(args)
        return await original_run_git(work_dir, *args)

    with patch("nuocode.worktree.create._run_git", side_effect=spy_run_git):
        wt2 = await mgr.create("restore-test", "HEAD", manual=True)

    # worktree add 不应该被调用
    worktree_add_calls = [c for c in run_git_calls if "add" in c]
    assert len(worktree_add_calls) == 0
    assert wt2.name == "restore-test"


# ── 创建后设置 A ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_setup_a_copy_settings(git_repo: Path) -> None:
    """设置 A：.nuocode/settings.local.yaml 被复制到 Worktree。"""
    nuocode_dir = git_repo / ".nuocode"
    nuocode_dir.mkdir(exist_ok=True)
    settings_file = nuocode_dir / "settings.local.yaml"
    settings_file.write_text("key: value\n")

    mgr = Manager(str(git_repo))
    wt = await mgr.create("setup-a", "HEAD", manual=True)

    dst = Path(wt.path) / ".nuocode" / "settings.local.yaml"
    assert dst.exists()
    assert dst.read_text() == "key: value\n"


# ── 创建后设置 B ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_setup_b_husky_hooks(git_repo: Path) -> None:
    """设置 B：主仓 .husky/ 存在时 Worktree git config 含 core.hooksPath。"""
    husky_dir = git_repo / ".husky"
    husky_dir.mkdir()

    mgr = Manager(str(git_repo))
    wt = await mgr.create("setup-b", "HEAD", manual=True)

    result = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=wt.path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert ".husky" in result.stdout


# ── 创建后设置 C ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_setup_c_symlink_node_modules(git_repo: Path) -> None:
    """设置 C：主仓 node_modules 存在时 Worktree 内为软链。"""
    nm = git_repo / "node_modules"
    nm.mkdir()

    mgr = Manager(str(git_repo))
    wt = await mgr.create("setup-c", "HEAD", manual=True)

    wt_nm = Path(wt.path) / "node_modules"
    assert wt_nm.is_symlink()


# ── 创建后设置 D ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_setup_d_include_ignored(git_repo: Path) -> None:
    """设置 D：.worktreeinclude 模式命中的 ignored 文件被复制到 Worktree。"""
    # 创建 .gitignore 忽略 .env
    (git_repo / ".gitignore").write_text(".env\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=git_repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "gitignore"], cwd=git_repo, capture_output=True)

    # 创建被忽略的 .env
    (git_repo / ".env").write_text("SECRET=123\n")

    # 创建 .worktreeinclude
    (git_repo / ".worktreeinclude").write_text("*.env\n")

    mgr = Manager(str(git_repo))
    wt = await mgr.create("setup-d", "HEAD", manual=True)

    dst = Path(wt.path) / ".env"
    assert dst.exists()
    assert "SECRET" in dst.read_text()
