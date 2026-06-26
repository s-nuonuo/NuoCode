"""tmux 后端实现（chap15 F15-F16）。"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
from typing import TYPE_CHECKING

from nuocode.team.types import BackendType

if TYPE_CHECKING:
    from nuocode.team.backend import SpawnRequest


class TmuxBackend:
    """tmux 执行后端（F15）。

    在 $TMUX 内：split-window -h 分屏
    在 $TMUX 外但 tmux 二进制可用：new-session -d（F16）
    """

    def type(self) -> BackendType:
        return BackendType.TMUX

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        """在 tmux 启动队员子进程（F15）。

        initial_prompt 不走命令行，由 spawn_teammate 预写入 mailbox。
        返回 (pane_id, agent_id)。
        """
        cmd = _build_member_cmd(req)

        if os.environ.get("TMUX"):
            # 在 tmux 会话内：分屏
            tmux_args = [
                "tmux", "split-window",
                "-h",
                "-P", "-F", "#{pane_id}",
                "--",
            ] + cmd
        else:
            # 在 tmux 外：先建 detached session，再在里面开 window
            # 简化：直接 new-session -d 然后在里面跑
            tmux_args = [
                "tmux", "new-session",
                "-d",
                "-s", f"nuocode-{req.team_name}-{req.member_name}",
                "-x", "220", "-y", "50",
                "--",
            ] + cmd

        try:
            proc = await asyncio.create_subprocess_exec(
                *tmux_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except Exception as e:
            raise RuntimeError(f"tmux spawn 失败: {e}") from e

        if proc.returncode != 0:
            err_msg = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"tmux 命令失败 (code={proc.returncode}): {err_msg}")

        pane_id = stdout.decode(errors="replace").strip()
        return pane_id, req.agent_id

    async def wake(self, pane_id: str, agent_id: str) -> None:  # noqa: ARG002
        """发送回车键触发目标 pane 的 stdin reader（F15）。"""
        if not pane_id:
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "tmux", "send-keys", "-t", pane_id, "", "Enter",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception as e:  # noqa: BLE001
            print(f"[team] tmux wake 失败 (pane={pane_id}): {e}", file=sys.stderr)

    async def kill(self, pane_id: str, agent_id: str) -> None:  # noqa: ARG002
        """杀死 pane（F15），忽略 pane 不存在错误。"""
        if not pane_id:
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "tmux", "kill-pane", "-t", pane_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception as e:  # noqa: BLE001
            print(f"[team] tmux kill-pane 失败 (pane={pane_id}): {e}", file=sys.stderr)


def _build_member_cmd(req: SpawnRequest) -> list[str]:
    """构造 --team-member 子进程命令（F15）。

    agent-id 必须传，子进程不需要读 config.json 找自己。
    """
    parts = [
        sys.executable, "-m", "nuocode",
        "--team-member",
        "--team", shlex.quote(req.team_name),
        "--member", shlex.quote(req.member_name),
        "--agent-id", shlex.quote(req.agent_id),
        "--session-dir", shlex.quote(req.session_dir),
        "--worktree", shlex.quote(req.worktree_path),
    ]
    if req.agent_type:
        parts += ["--agent-type", shlex.quote(req.agent_type)]
    if req.model:
        parts += ["--model", shlex.quote(req.model)]
    if req.plan_mode_required:
        parts.append("--plan-mode")
    return parts
