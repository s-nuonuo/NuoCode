"""TeamHook Protocol、TeammateContext 与 IncomingMessage（chap15 T16）。

避免循环导入：agent 包不直接 import team 包的具体类型，
而是通过 Protocol 和闭包抽象。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

# ── Protocol ──────────────────────────────────────────────────────────────────

class TeamHook(Protocol):
    """Agent 工具委托给 Team Manager 的接口（plan.md）。"""

    async def spawn_teammate(self, req: TeamSpawnRequest) -> str:
        """spawn 队员，返回 JSON 描述字符串。"""
        ...

    def is_teammate_context(self, ctx: Any) -> tuple[str, str, bool]:
        """判断 ctx 是否在队员上下文中。

        返回 (team_name, member_name, is_in_process)。
        若不在队员上下文，返回 ("", "", False)。
        """
        ...


# ── 请求结构 ──────────────────────────────────────────────────────────────────

@dataclass
class TeamSpawnRequest:
    """Agent 工具 team_name 分支传给 TeamHook 的参数（T16）。"""

    team_name: str
    member_name: str
    subagent_type: str
    model: str
    prompt: str
    description: str
    plan_mode_required: bool = False
    run_in_background: bool = False  # Team 队员忽略，始终 background


# ── TeammateContext ───────────────────────────────────────────────────────────

@dataclass
class IncomingMessage:
    """轻量 incoming message（agent 包内用，避免 import mailbox.Message）。"""

    from_: str
    to: str
    type: str
    summary: str
    content: str
    payload: dict[str, Any] | None = None
    timestamp: int = 0


@dataclass
class TeammateContext:
    """队员执行上下文（T16）。

    由 spawn 时注入到 Agent，在 Loop 头部读 mailbox。
    使用闭包避免 agent 包直接依赖 team.mailbox。
    """

    team_name: str
    member_name: str
    agent_id: str
    mailbox_dir: str
    backend_type: str = "in-process"

    # 闭包接口（由 team 包在 spawn 时注入）
    read_unread: Callable[[], Awaitable[tuple[list[int], list[IncomingMessage]]]] = field(
        default=lambda: _noop_read_unread(),  # type: ignore[assignment]
        repr=False,
    )
    mark_read: Callable[[list[int]], Awaitable[None]] = field(
        default=lambda indices: _noop_mark_read(indices),  # type: ignore[assignment]
        repr=False,
    )


async def _noop_read_unread() -> tuple[list[int], list[IncomingMessage]]:
    return [], []


async def _noop_mark_read(indices: list[int]) -> None:
    pass


# ── ctx 存取工具 ──────────────────────────────────────────────────────────────

WITH_TEAMMATE_KEY = "teammate_context"


def with_teammate_context(ctx: dict, tc: TeammateContext) -> dict:
    """在 ctx 中注入 TeammateContext，返回新 dict。"""
    new_ctx = dict(ctx)
    new_ctx[WITH_TEAMMATE_KEY] = tc
    return new_ctx


def teammate_context_from_ctx(ctx: Any) -> TeammateContext | None:
    """从 ctx 取 TeammateContext，不存在返回 None。"""
    if isinstance(ctx, dict):
        return ctx.get(WITH_TEAMMATE_KEY)
    return None
