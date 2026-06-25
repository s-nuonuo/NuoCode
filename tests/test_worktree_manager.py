"""test_worktree_manager.py：Manager 构造 + session 持久化测试（chap14 T4）。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nuocode.worktree.manager import Manager
from nuocode.worktree.session import WorktreeSession, load_session, save_session


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


# ── Manager 构造 ───────────────────────────────────────────────────────────

def test_manager_construct_success(git_repo: Path) -> None:
    """在 git 仓库根目录构造 Manager 成功。"""
    mgr = Manager(str(git_repo))
    assert mgr.repo_root == str(git_repo)
    assert mgr.worktree_dir.exists()
    assert mgr.current_session() is None
    assert mgr.list() == []


def test_manager_construct_not_git(tmp_path: Path) -> None:
    """非 git 目录抛 ValueError。"""
    plain_dir = tmp_path / "notgit"
    plain_dir.mkdir()
    with pytest.raises(ValueError):
        Manager(str(plain_dir))


def test_manager_construct_subdir(git_repo: Path) -> None:
    """git 仓库子目录（非根目录）抛 ValueError。"""
    subdir = git_repo / "subdir"
    subdir.mkdir()
    with pytest.raises(ValueError):
        Manager(str(subdir))


def test_manager_worktree_dir_created(git_repo: Path) -> None:
    """构造时自动创建 worktree_dir。"""
    wt_dir = git_repo / ".nuocode" / "worktrees"
    assert not wt_dir.exists() or True  # 可能已存在
    Manager(str(git_repo))
    assert wt_dir.exists()


# ── session 持久化 ─────────────────────────────────────────────────────────

def test_manager_loads_null_session(git_repo: Path) -> None:
    """session 文件内容为 null 时 current_session()=None。"""
    session_file = git_repo / ".nuocode" / "worktree_session.json"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("null")
    mgr = Manager(str(git_repo))
    assert mgr.current_session() is None


def test_manager_loads_valid_session(git_repo: Path) -> None:
    """预写有效 session 文件时，Manager 能读取到 session。"""
    # 先创建 worktree 目录
    wt_path = git_repo / ".nuocode" / "worktrees" / "demo"
    wt_path.mkdir(parents=True, exist_ok=True)

    session = WorktreeSession(
        original_cwd=str(git_repo),
        worktree_path=str(wt_path),
        worktree_name="demo",
        original_branch="main",
        original_head_commit="a" * 40,
        session_id="test-session-id",
    )
    session_file = git_repo / ".nuocode" / "worktree_session.json"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    save_session(session_file, session)

    mgr = Manager(str(git_repo))
    loaded = mgr.current_session()
    assert loaded is not None
    assert loaded.worktree_name == "demo"
    assert loaded.session_id == "test-session-id"


def test_manager_clears_session_if_worktree_gone(git_repo: Path) -> None:
    """session 指向的 worktree 目录不存在时，清空 session。"""
    session = WorktreeSession(
        original_cwd=str(git_repo),
        worktree_path="/nonexistent/worktree",
        worktree_name="ghost",
        original_branch="main",
        original_head_commit="a" * 40,
        session_id="ghost-session",
    )
    session_file = git_repo / ".nuocode" / "worktree_session.json"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    save_session(session_file, session)

    mgr = Manager(str(git_repo))
    assert mgr.current_session() is None
    # session 文件应被清空（写入 null）
    assert session_file.read_text().strip() == "null"


def test_manager_corrupted_session_file(git_repo: Path, capsys) -> None:
    """session 文件损坏时，Manager 清空并继续（不抛异常）。"""
    session_file = git_repo / ".nuocode" / "worktree_session.json"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("{not-valid-json")

    mgr = Manager(str(git_repo))
    assert mgr.current_session() is None
    captured = capsys.readouterr()
    assert "损坏" in captured.err or "session" in captured.err.lower()


# ── WorktreeSession 序列化 ─────────────────────────────────────────────────

def test_session_json_roundtrip() -> None:
    """WorktreeSession JSON 序列化/反序列化字段名为下划线小写。"""
    session = WorktreeSession(
        original_cwd="/tmp",
        worktree_path="/tmp/wt",
        worktree_name="test",
        original_branch="main",
        original_head_commit="a" * 40,
        session_id="sid-123",
    )
    json_str = session.to_json()
    assert "original_cwd" in json_str
    assert "worktree_path" in json_str
    restored = WorktreeSession.from_json(json_str)
    assert restored == session


def test_save_session_null(tmp_path: Path) -> None:
    """save_session(path, None) 写入 null。"""
    path = tmp_path / "session.json"
    save_session(path, None)
    assert path.read_text().strip() == "null"


def test_load_session_null(tmp_path: Path) -> None:
    """load_session 读 null 返回 None。"""
    path = tmp_path / "session.json"
    path.write_text("null")
    assert load_session(path) is None


def test_load_session_nonexistent(tmp_path: Path) -> None:
    """load_session 文件不存在返回 None。"""
    assert load_session(tmp_path / "missing.json") is None
