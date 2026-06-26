"""Team 包基础类型（chap15 F1-F4, F11-F13）。

定义：
- BackendType：三种执行后端枚举
- Team：团队数据结构
- TeammateInfo：队员信息
- 各类异常
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

# ── 后端类型 ─────────────────────────────────────────────────────────────────

class BackendType(StrEnum):
    """执行后端类型（F11）。"""

    TMUX = "tmux"
    ITERM2 = "iterm2"
    IN_PROCESS = "in-process"


# ── 数据类 ───────────────────────────────────────────────────────────────────

@dataclass
class TeammateInfo:
    """队员信息（F2）。

    is_active 语义：
    - None / True：活跃（正在运行或刚创建）
    - False：空闲（已完成或已停止）
    """

    name: str                               # Lead 分配的队员名，Team 内唯一
    agent_id: str                           # 对应 task.BackgroundTask.id
    agent_type: str = ""                    # 角色定义名；Fork 路径下为 ""
    model: str = ""                         # 模型覆盖；空表示 inherit
    worktree_path: str = ""                 # 绝对路径
    branch: str = ""                        # 对应 worktree 分支名
    backend_type: BackendType | str = BackendType.IN_PROCESS
    pane_id: str = ""                       # tmux pane id / iterm2 split id / "" for in-process
    is_active: bool | None = None           # None/True 活跃，False 空闲
    plan_mode_required: bool = False
    session_dir: str = ""                   # 队员独立 session 目录绝对路径

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 兼容 dict。"""
        return {
            "name": self.name,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "model": self.model,
            "worktree_path": self.worktree_path,
            "branch": self.branch,
            "backend_type": str(self.backend_type),
            "pane_id": self.pane_id,
            "is_active": self.is_active,
            "plan_mode_required": self.plan_mode_required,
            "session_dir": self.session_dir,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TeammateInfo:
        """从 dict 反序列化。"""
        backend_raw = d.get("backend_type", "in-process")
        try:
            backend = BackendType(backend_raw)
        except ValueError:
            backend = BackendType.IN_PROCESS

        return cls(
            name=d.get("name", ""),
            agent_id=d.get("agent_id", ""),
            agent_type=d.get("agent_type", ""),
            model=d.get("model", ""),
            worktree_path=d.get("worktree_path", ""),
            branch=d.get("branch", ""),
            backend_type=backend,
            pane_id=d.get("pane_id", ""),
            is_active=d.get("is_active"),   # 保持 None/True/False 语义
            plan_mode_required=bool(d.get("plan_mode_required", False)),
            session_dir=d.get("session_dir", ""),
        )


@dataclass
class Team:
    """团队数据结构（F1）。

    config_dir / config_path / tasks_path / mailbox_dir 是派生路径，
    从 config_dir 算出，不持久化到 JSON（加载时重新算）。
    """

    name: str                               # 用户给的原始名
    sanitized_name: str                     # 经 sanitize 后用于路径，Team 主键
    lead_agent_id: str                      # 固定 "lead"（本期 Lead = 主 Agent）
    backend: BackendType | str = BackendType.IN_PROCESS  # 全 team 默认后端
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    members: list[TeammateInfo] = field(default_factory=list)

    # 派生路径（不持久化）
    config_dir: str = ""
    config_path: str = ""                   # <config_dir>/config.json
    tasks_path: str = ""                    # <config_dir>/tasks.json
    mailbox_dir: str = ""                   # <config_dir>/mailbox/

    # 并发锁（不持久化，repr=False 避免递归打印）
    _lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, repr=False, compare=False
    )

    def member_by_name(self, name: str) -> TeammateInfo | None:
        """按 name 查队员。"""
        for m in self.members:
            if m.name == name:
                return m
        return None

    def member_by_agent_id(self, agent_id: str) -> TeammateInfo | None:
        """按 agent_id 查队员。"""
        for m in self.members:
            if m.agent_id == agent_id:
                return m
        return None

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 兼容 dict（不含派生路径与锁）。"""
        return {
            "name": self.name,
            "sanitized_name": self.sanitized_name,
            "lead_agent_id": self.lead_agent_id,
            "backend": str(self.backend),
            "description": self.description,
            "created_at": self.created_at.timestamp(),
            "members": [m.to_dict() for m in self.members],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any], config_dir: str) -> Team:
        """从 dict 反序列化（config_dir 在磁盘恢复时传入）。"""
        import os

        backend_raw = d.get("backend", "in-process")
        try:
            backend = BackendType(backend_raw)
        except ValueError:
            backend = BackendType.IN_PROCESS

        created_ts = d.get("created_at", 0)
        try:
            created_at = datetime.fromtimestamp(float(created_ts))
        except (ValueError, TypeError, OSError):
            created_at = datetime.now()

        members_raw = d.get("members", [])
        members = [TeammateInfo.from_dict(m) for m in members_raw]

        team = cls(
            name=d.get("name", ""),
            sanitized_name=d.get("sanitized_name", ""),
            lead_agent_id=d.get("lead_agent_id", "lead"),
            backend=backend,
            description=d.get("description", ""),
            created_at=created_at,
            members=members,
            config_dir=config_dir,
        )
        # 填充派生路径
        team.config_path = os.path.join(config_dir, "config.json")
        team.tasks_path = os.path.join(config_dir, "tasks.json")
        team.mailbox_dir = os.path.join(config_dir, "mailbox")
        return team


# ── 异常类 ───────────────────────────────────────────────────────────────────

class TeamError(Exception):
    """Team 相关异常基类。"""


class TeamNotFoundError(TeamError):
    """找不到指定 Team。"""


class TeamHasActiveMembersError(TeamError):
    """Team 有活跃成员，无法删除。"""


class MemberExistsError(TeamError):
    """队员名已存在。"""


class MemberNotFoundError(TeamError):
    """找不到指定队员。"""


class InProcessTeammateNoSpawnError(TeamError):
    """in-process 队员不允许再 spawn Team 队员。"""
