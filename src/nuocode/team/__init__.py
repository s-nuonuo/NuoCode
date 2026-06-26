"""nuocode.team 包导出（chap15）。"""

from __future__ import annotations

from nuocode.team.manager import LeadMessage, Manager
from nuocode.team.registry import AgentNameRegistry
from nuocode.team.types import (
    BackendType,
    InProcessTeammateNoSpawnError,
    MemberExistsError,
    MemberNotFoundError,
    Team,
    TeamError,
    TeamHasActiveMembersError,
    TeammateInfo,
    TeamNotFoundError,
)

__all__ = [
    "Manager",
    "LeadMessage",
    "AgentNameRegistry",
    "Team",
    "TeammateInfo",
    "BackendType",
    "TeamError",
    "TeamNotFoundError",
    "TeamHasActiveMembersError",
    "MemberExistsError",
    "MemberNotFoundError",
    "InProcessTeammateNoSpawnError",
]
