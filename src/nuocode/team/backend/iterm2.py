"""iTerm2 后端实现（chap15 F17）。"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

from nuocode.team.types import BackendType

if TYPE_CHECKING:
    from nuocode.team.backend import SpawnRequest


class Iterm2Backend:
    """iTerm2 执行后端（F17）。

    通过 it2 CLI 控制 iTerm2 分屏。
    注意：CI 环境无法实跑，以构造正确命令字符串为目标。
    """

    def type(self) -> BackendType:
        return BackendType.ITERM2

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        """在 iTerm2 启动队员子进程（F17）。

        initial_prompt 不走命令行，由 spawn_teammate 预写入 mailbox。
        返回 (pane_id, agent_id)。
        """
        from nuocode.team.backend.tmux import _build_member_cmd

        cmd_parts = _build_member_cmd(req)
        # it2 split --new-pane --command "<cmd>"
        cmd_str = " ".join(cmd_parts)

        try:
            proc = await asyncio.create_subprocess_exec(
                "it2", "split", "--new-pane", "--command", cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except Exception as e:
            raise RuntimeError(f"it2 spawn 失败: {e}") from e

        if proc.returncode != 0:
            err_msg = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"it2 命令失败 (code={proc.returncode}): {err_msg}")

        pane_id = stdout.decode(errors="replace").strip()
        return pane_id, req.agent_id

    async def wake(self, pane_id: str, agent_id: str) -> None:  # noqa: ARG002
        """发送空文本唤醒目标 pane（F17）。"""
        if not pane_id:
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "it2", "send-text", "--pane", pane_id, "",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception as e:  # noqa: BLE001
            print(f"[team] it2 wake 失败 (pane={pane_id}): {e}", file=sys.stderr)

    async def kill(self, pane_id: str, agent_id: str) -> None:  # noqa: ARG002
        """关闭 pane（F17）。"""
        if not pane_id:
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "it2", "close-pane", "--pane", pane_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception as e:  # noqa: BLE001
            print(f"[team] it2 kill-pane 失败 (pane={pane_id}): {e}", file=sys.stderr)
