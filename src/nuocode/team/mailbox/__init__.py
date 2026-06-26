"""邮箱 Box 类（chap15 F33）。

提供 write/read/read_unread/mark_read 接口，内置文件锁并发安全。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from nuocode.team.filelock import acquire
from nuocode.team.mailbox.message import Message

if TYPE_CHECKING:
    pass


class Box:
    """邮箱操作类（F33）。

    所有操作都走文件锁，跨进程并发安全。
    """

    def __init__(self, dir_: str) -> None:
        """初始化邮箱，确保目录存在。"""
        self._dir = str(dir_)
        Path(self._dir).mkdir(parents=True, exist_ok=True)

    def _mailbox_path(self, agent_id: str) -> str:
        return os.path.join(self._dir, f"{agent_id}.json")

    def _lock_path(self, agent_id: str) -> str:
        return os.path.join(self._dir, f"{agent_id}.lock")

    async def write(self, agent_id: str, msg: Message) -> None:
        """向 agent 的邮箱写入消息（F33）。

        并发安全：持文件锁，read-modify-write，os.replace 原子替换。
        """
        from nuocode.team.persistence import atomic_write_json

        lock_path = self._lock_path(agent_id)
        mailbox_path = self._mailbox_path(agent_id)

        async with acquire(lock_path):
            # 读现有消息
            try:
                with open(mailbox_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                data = {"messages": []}

            # 设置 timestamp
            if msg.timestamp == 0:
                msg.timestamp = int(time.time())

            # 追加消息
            messages = data.get("messages", [])
            messages.append(msg.to_dict())
            data["messages"] = messages

            # 原子写
            atomic_write_json(mailbox_path, data)

    async def read(self, agent_id: str) -> list[Message]:
        """读取 agent 的所有消息（F33）。"""
        mailbox_path = self._mailbox_path(agent_id)
        try:
            with open(mailbox_path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        return [Message.from_dict(m) for m in data.get("messages", [])]

    async def read_unread(self, agent_id: str) -> tuple[list[int], list[Message]]:
        """读取未读消息，返回 (indices, messages)（F33）。"""
        all_messages = await self.read(agent_id)
        indices = [i for i, m in enumerate(all_messages) if not m.read]
        unread = [all_messages[i] for i in indices]
        return indices, unread

    async def mark_read(self, agent_id: str, indices: list[int]) -> None:
        """将指定 indices 的消息标记为已读（F33）。"""
        from nuocode.team.persistence import atomic_write_json

        if not indices:
            return

        lock_path = self._lock_path(agent_id)
        mailbox_path = self._mailbox_path(agent_id)

        async with acquire(lock_path):
            try:
                with open(mailbox_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return

            messages = data.get("messages", [])
            idx_set = set(indices)
            for i in idx_set:
                if 0 <= i < len(messages):
                    messages[i]["read"] = True

            data["messages"] = messages
            atomic_write_json(mailbox_path, data)
