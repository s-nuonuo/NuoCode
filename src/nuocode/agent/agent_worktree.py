"""_execute_with_worktree + build_worktree_notice（chap14 F21-F22/T11）。

SubAgent isolation:worktree 的执行分支：
1. 用随机名生成临时 Worktree
2. 拼 worktree-context 系统提示
3. 用 with_cwd 注入 ctx cwd
4. run_to_completion 跑子 Agent
5. auto_cleanup 清理或保留
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from nuocode.tool.ctx import with_cwd
from nuocode.worktree import Manager, random_agent_name

if TYPE_CHECKING:
    pass


def build_worktree_notice(parent_cwd: str, wt_path: str) -> str:
    """构建 worktree-context 提示文本（spec F22）。"""
    return (
        "<worktree-context>\n"
        "你当前在一个独立的 Git Worktree 副本中工作，与父 Agent 隔离。\n"
        f"- 父目录: {parent_cwd}\n"
        f"- 你的工作目录: {wt_path}\n"
        "- 父 Agent 提到的绝对路径基于父目录，你需要翻译成本地路径（替换前缀）再读写\n"
        "- 编辑文件前，必须先在本地 Worktree 重新 `read_file` 一次，避免使用过时内容\n"
        "</worktree-context>"
    )


async def _execute_with_worktree(
    manager: Manager,
    definition: Any,           # subagent.Definition
    sub_agent: Any,            # agent.Agent
    sub_conv: Any,             # Conversation
    prompt: str,
) -> str:
    """在独立 Worktree 中执行子 Agent（spec F21）。

    步骤：
    1. random_agent_name → worktree_mgr.create
    2. 拼 worktree_notice + task_text
    3. with_cwd(wt.path) 包住 run_to_completion
    4. auto_cleanup：有变更时追加保留信息到返回文本
    """
    name = random_agent_name()
    wt = await manager.create(name, "HEAD", manual=False)

    parent_cwd = str(Path.cwd())
    notice = build_worktree_notice(parent_cwd, wt.path)
    task_text = notice + "\n\n" + prompt

    from nuocode.agent import MaxTurnsReached

    final_text = ""
    with with_cwd(wt.path):
        try:
            final_text = await sub_agent.run_to_completion(sub_conv, task_text)
        except MaxTurnsReached as e:
            final_text = e.final_text

    report = await manager.auto_cleanup(name)
    if report.kept:
        final_text += f"\n[Worktree 保留: {report.path}，分支 {report.branch}]"

    return final_text
