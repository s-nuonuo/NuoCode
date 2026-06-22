"""hook.rule: 数据结构——Rule / Condition / Action / Payload（chap12）。"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nuocode.hook.event import Event

if TYPE_CHECKING:
    from nuocode.permission.matcher import Matcher

# ────────── 枚举 ──────────


class CombineMode(str, enum.Enum):
    ALL_OF = "all_of"
    ANY_OF = "any_of"


class ActionType(str, enum.Enum):
    SHELL = "shell"
    PROMPT = "prompt"
    HTTP = "http"
    SUBAGENT = "subagent"


# ────────── 条件 ──────────


@dataclass
class AtomCondition:
    """单条原子条件：对 payload 中某字段的路径值用 Matcher 进行匹配。"""

    field: str          # 字段路径，如 "tool_name" 或 "tool_input.path"
    matcher: "Matcher"  # 复用 permission.Matcher


@dataclass
class Condition:
    """组合条件：all_of（全部满足）或 any_of（至少一个满足）。"""

    mode: CombineMode
    atoms: list[AtomCondition]


# ────────── 动作 ──────────


@dataclass
class ShellAction:
    command: str    # 由 sh -c 解释执行


@dataclass
class PromptAction:
    text: str       # 注入到下一轮 LLM reminder 区的文本


@dataclass
class HttpAction:
    url: str
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None     # 模板字符串（str.format_map），None 表示用 payload JSON


@dataclass
class SubagentAction:
    agent_name: str
    prompt: str


@dataclass
class Action:
    type: ActionType
    shell: ShellAction | None = None
    prompt: PromptAction | None = None
    http: HttpAction | None = None
    subagent: SubagentAction | None = None


# ────────── 规则 ──────────


@dataclass
class Rule:
    name: str
    event: Event
    action: Action
    condition: Condition | None = None  # None 表示无条件触发
    only_once: bool = False
    asyncio_mode: bool = False          # 对应 YAML 的 `async`（避免与 Python 关键字冲突）
    timeout_s: float = 30.0
    source: str = ""                    # 来源文件路径，供 /hooks 显示


# ────────── Payload ──────────

Payload = dict[str, Any]
"""事件分派时携带的上下文数据。序列化时用 json.dumps(payload, sort_keys=True) 保证字段顺序。"""


__all__ = [
    "Action",
    "ActionType",
    "AtomCondition",
    "CombineMode",
    "Condition",
    "HttpAction",
    "Payload",
    "PromptAction",
    "Rule",
    "ShellAction",
    "SubagentAction",
]
