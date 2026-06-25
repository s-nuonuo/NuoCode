"""test_agent_worktree.py：_execute_with_worktree + build_worktree_notice 单测（chap14 T11）。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nuocode.agent.agent_worktree import _execute_with_worktree, build_worktree_notice
from nuocode.tool.ctx import cwd_from_ctx
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


# ── build_worktree_notice ─────────────────────────────────────────────────

def test_build_worktree_notice_contains_tags() -> None:
    notice = build_worktree_notice("/parent/cwd", "/wt/path")
    assert "<worktree-context>" in notice
    assert "</worktree-context>" in notice
    assert "/parent/cwd" in notice
    assert "/wt/path" in notice


def test_build_worktree_notice_fields() -> None:
    notice = build_worktree_notice("/foo/bar", "/wt/baz")
    assert "父目录" in notice
    assert "工作目录" in notice


# ── _execute_with_worktree ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_with_worktree_basic(git_repo: Path) -> None:
    """_execute_with_worktree 创建 Worktree，注入 ctx cwd，调用 run_to_completion，然后 auto_cleanup。"""
    mgr = Manager(str(git_repo))

    received_cwd: list[str | None] = []

    async def mock_run_to_completion(conv: object, task: str) -> str:
        # 记录调用时的 ctx cwd
        received_cwd.append(cwd_from_ctx())
        return "done"

    mock_agent = MagicMock()
    mock_agent.run_to_completion = mock_run_to_completion

    from nuocode.conversation import Conversation

    result = await _execute_with_worktree(
        manager=mgr,
        definition=MagicMock(name="test"),
        sub_agent=mock_agent,
        sub_conv=Conversation(),
        prompt="test prompt",
    )

    assert result == "done"  # auto_cleanup 无变更，不追加保留信息
    # ctx cwd 应该是 worktree 路径
    assert received_cwd[0] is not None
    assert ".nuocode/worktrees/agent-a" in received_cwd[0]


@pytest.mark.asyncio
async def test_execute_with_worktree_kept_on_changes(git_repo: Path) -> None:
    """子 Agent 写文件后，auto_cleanup kept=True，结果末尾追加保留信息。"""
    mgr = Manager(str(git_repo))

    async def mock_run_to_completion(conv: object, task: str) -> str:
        # 在 worktree 里写一个文件
        wt_path = cwd_from_ctx()
        if wt_path:
            (Path(wt_path) / "sub_output.txt").write_text("from sub agent\n")
        return "sub done"

    mock_agent = MagicMock()
    mock_agent.run_to_completion = mock_run_to_completion

    from nuocode.conversation import Conversation

    result = await _execute_with_worktree(
        manager=mgr,
        definition=MagicMock(name="test"),
        sub_agent=mock_agent,
        sub_conv=Conversation(),
        prompt="write a file",
    )

    assert "sub done" in result
    assert "Worktree 保留" in result


@pytest.mark.asyncio
async def test_execute_with_worktree_notice_in_task(git_repo: Path) -> None:
    """worktree_notice 被拼入 task_text 传给 run_to_completion。"""
    mgr = Manager(str(git_repo))

    received_task: list[str] = []

    async def mock_run_to_completion(conv: object, task: str) -> str:
        received_task.append(task)
        return "ok"

    mock_agent = MagicMock()
    mock_agent.run_to_completion = mock_run_to_completion

    from nuocode.conversation import Conversation

    await _execute_with_worktree(
        manager=mgr,
        definition=MagicMock(),
        sub_agent=mock_agent,
        sub_conv=Conversation(),
        prompt="do something",
    )

    assert received_task  # 至少调用了一次
    task_text = received_task[0]
    assert "<worktree-context>" in task_text
    assert "do something" in task_text
