"""命令类型定义：Kind 枚举 + Command dataclass + Handler 类型别名。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nuocode.command.ui import UI


class Kind(Enum):
    """命令执行类型。

    - ``LOCAL``：纯本地查询，仅打印；不改 App、不进 history、不消耗 token。
    - ``UI``：影响界面（切模式、退出、压缩、resume、clear 等）；不进 history。
    - ``PROMPT``：注入一条 user 消息并立即触发回合；进 history 与会话存档。
    """

    LOCAL = "local"
    UI = "ui"
    PROMPT = "prompt"


Handler = Callable[["UI"], Awaitable[None]]


@dataclass(slots=True)
class Command:
    """注册中心条目。"""

    name: str
    description: str
    kind: Kind
    handler: Handler
    aliases: list[str] = field(default_factory=list)
    hidden: bool = False
    is_skill: bool = False


__all__ = ["Command", "Handler", "Kind"]
