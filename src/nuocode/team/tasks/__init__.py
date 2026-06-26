"""共享任务列表 Store（chap15 F26-F30）。

使用 tasks.json 持久化，文件锁并发安全。
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    """任务状态（F30）。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class Task:
    """任务数据结构（F30）。"""

    id: str
    title: str
    description: str = ""
    status: Status = Status.PENDING
    assignee: str = ""
    blocked_by: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": str(self.status),
            "assignee": self.assignee,
            "blocked_by": list(self.blocked_by),
            "blocks": list(self.blocks),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Task:
        status_raw = d.get("status", "pending")
        try:
            status = Status(status_raw)
        except ValueError:
            status = Status.PENDING
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            status=status,
            assignee=d.get("assignee", ""),
            blocked_by=list(d.get("blocked_by", [])),
            blocks=list(d.get("blocks", [])),
            created_at=d.get("created_at", 0),
            updated_at=d.get("updated_at", 0),
        )


@dataclass
class Filter:
    """任务过滤条件（F28）。"""

    status: Status | str | None = None


@dataclass
class Patch:
    """任务更新补丁（F29）。"""

    title: str | None = None
    description: str | None = None
    status: Status | str | None = None
    assignee: str | None = None
    add_blocks: list[str] = field(default_factory=list)
    add_blocked_by: list[str] = field(default_factory=list)
    remove_blocks: list[str] = field(default_factory=list)
    remove_blocked_by: list[str] = field(default_factory=list)


class Store:
    """任务存储（F26-F30）。

    使用 tasks.json 持久化，文件锁并发安全。
    """

    def __init__(self, path: str) -> None:
        """初始化 Store。

        path: tasks.json 文件路径
        """
        self._path = str(path)
        self._lock_path = str(path) + ".lock"
        self._asyncio_lock = asyncio.Lock()

    def _read_all(self) -> list[Task]:
        """从磁盘读取所有任务。"""
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        return [Task.from_dict(t) for t in data.get("tasks", [])]

    def _write_all(self, tasks: list[Task]) -> None:
        """原子写所有任务到磁盘。"""
        from nuocode.team.persistence import atomic_write_json

        atomic_write_json(self._path, {"tasks": [t.to_dict() for t in tasks]})

    async def create(self, t: Task) -> str:
        """创建任务，返回 task_id（F26）。"""
        from nuocode.team.filelock import acquire

        task_id = f"task_{secrets.token_hex(3)}"
        t.id = task_id
        now = int(time.time())
        t.created_at = now
        t.updated_at = now

        async with acquire(self._lock_path):
            tasks = self._read_all()
            tasks.append(t)
            self._write_all(tasks)

        return task_id

    async def get(self, id_: str) -> Task:
        """获取任务（F27）。"""
        tasks = self._read_all()
        for t in tasks:
            if t.id == id_:
                return t
        raise KeyError(f"任务不存在: {id_!r}")

    async def list_(self, f: Filter | None = None) -> list[dict[str, Any]]:
        """列出任务，附加 is_ready 字段（F28）。"""
        tasks = self._read_all()

        # 过滤
        if f is not None and f.status is not None:
            status_str = str(f.status)
            tasks = [t for t in tasks if str(t.status) == status_str]

        # 构建 id → Task 映射以计算 is_ready
        all_tasks = {t.id: t for t in self._read_all()}

        result = []
        for t in tasks:
            d = t.to_dict()
            # is_ready：blocked_by 中所有任务都已 completed
            is_ready = all(
                all_tasks.get(bid, Task(id=bid, title="")).status == Status.COMPLETED
                for bid in t.blocked_by
            )
            d["is_ready"] = is_ready
            result.append(d)

        return result

    async def update(self, id_: str, p: Patch) -> None:
        """更新任务（F29）。

        add_blocked_by 同时给对方 tasks.blocks 加上当前任务 id（双向维护）。
        """
        from nuocode.team.filelock import acquire

        async with acquire(self._lock_path):
            tasks = self._read_all()
            task_map = {t.id: t for t in tasks}

            target = task_map.get(id_)
            if target is None:
                raise KeyError(f"任务不存在: {id_!r}")

            now = int(time.time())
            target.updated_at = now

            if p.title is not None:
                target.title = p.title
            if p.description is not None:
                target.description = p.description
            if p.status is not None:
                try:
                    target.status = Status(str(p.status))
                except ValueError:
                    target.status = p.status  # type: ignore[assignment]
            if p.assignee is not None:
                target.assignee = p.assignee

            # add_blocks
            for bid in p.add_blocks:
                if bid not in target.blocks:
                    target.blocks.append(bid)
                # 双向：给 bid 的 blocked_by 加上 id_
                other = task_map.get(bid)
                if other and id_ not in other.blocked_by:
                    other.blocked_by.append(id_)

            # add_blocked_by（F29 双向维护）
            for bid in p.add_blocked_by:
                if bid not in target.blocked_by:
                    target.blocked_by.append(bid)
                # 双向：给 bid 的 blocks 加上 id_
                other = task_map.get(bid)
                if other and id_ not in other.blocks:
                    other.blocks.append(id_)

            # remove_blocks
            for bid in p.remove_blocks:
                target.blocks = [b for b in target.blocks if b != bid]
                other = task_map.get(bid)
                if other:
                    other.blocked_by = [b for b in other.blocked_by if b != id_]

            # remove_blocked_by
            for bid in p.remove_blocked_by:
                target.blocked_by = [b for b in target.blocked_by if b != bid]
                other = task_map.get(bid)
                if other:
                    other.blocks = [b for b in other.blocks if b != id_]

            self._write_all(list(task_map.values()))
