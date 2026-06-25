"""SubAgent 角色定义数据结构（chap13）。

定义 ``Source`` 来源枚举与 ``Definition`` dataclass，
对应 spec F4 / plan.md 核心数据结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from nuocode.permission import Mode


class Source(IntEnum):
    """Agent 定义文件来源，数值越大优先级越高。"""

    BUILTIN = 0   # 随包发布的内置角色
    USER = 1      # 用户级 ~/.nuocode/agents/
    PROJECT = 2   # 项目级 <root>/.nuocode/agents/
    PLUGIN = 3    # 插件来源（本期恒为空，占位）

    def __str__(self) -> str:
        return {
            0: "builtin",
            1: "user",
            2: "project",
            3: "plugin",
        }.get(int(self), "unknown")


@dataclass
class Definition:
    """一个 Agent 角色的完整定义，从 Markdown+YAML frontmatter 解析。

    字段语义（spec F4）：
    - ``name``：角色名，小写字母/数字/连字符，长度 1-32（或首字母大写，见 AGENT_NAME_REGEX）
    - ``description``：一句话描述，用于 UI 展示与 Agent 工具的 subagent_type 文档
    - ``tools``：工具白名单；空列表表示不收窄
    - ``disallowed_tools``：工具黑名单
    - ``model``：haiku/sonnet/opus/inherit，缺省 inherit
    - ``max_turns``：最大迭代轮数；0 表示沿用全局默认（25）
    - ``permission_mode``：权限模式；配合 ``dont_ask`` 使用
    - ``dont_ask``：permissionMode=dontAsk 时置 True，绕过 Ask 直接 Allow
    - ``background``：强制后台执行
    - ``system_prompt``：Markdown body（去 frontmatter 后的全文）作为子 Agent 系统提示
    - ``file_path``：定义文件绝对路径，用于调试
    - ``source``：来源枚举
    """

    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    model: str = "inherit"
    max_turns: int = 0
    permission_mode: Mode = Mode.DEFAULT
    dont_ask: bool = False
    background: bool = False
    system_prompt: str = ""
    file_path: str = ""
    source: Source = Source.BUILTIN

    def is_fork(self) -> bool:
        """判断是否为 Fork 路径用的临时定义（spec F22）。"""
        return self.name == "__fork__"
