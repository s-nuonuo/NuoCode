"""工具过滤多层防线（chap13 + chap15）。

定义子 Agent 工具列表过滤的常量与逻辑，对应 spec F26-F30。

过滤顺序（``apply_agent_tool_filter``）：
1. 起点 = registry 全量工具名
2. 去掉 ``ALL_AGENT_DISALLOWED_TOOLS``（任何子 Agent 永远不能用）
3. 若非内置来源，额外去掉 ``CUSTOM_AGENT_DISALLOWED_TOOLS``（本期为空）
4. 若后台模式，与 ``ASYNC_AGENT_ALLOWED_TOOLS`` + MCP/Skill 工具命名约定取交集
5. 应用定义层 ``disallowed_tools`` 黑名单
6. 若 ``allowed`` 白名单非空，与之取交集
7. 若 ``teammate=True``，注入 ``TEAMMATE_EXTRA_TOOLS``（chap15 T17）
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── 常量 ────────────────────────────────────────────────────────────────────

# 任何子 Agent 永远不能调用的工具（spec F26）。
# 本期最小列表：Agent（从根源断绝嵌套）。
ALL_AGENT_DISALLOWED_TOOLS: list[str] = ["Agent"]

# 自定义（user/project/plugin）Agent 额外禁用的工具（spec F27，本期为空）。
CUSTOM_AGENT_DISALLOWED_TOOLS: list[str] = []

# 后台 Agent 工具白名单（spec F28）。
# 不含 Agent/TaskList/TaskGet/TaskStop/SendMessage 等元工具。
ASYNC_AGENT_ALLOWED_TOOLS: list[str] = [
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
    "bash",
    "load_skill",
    "install_skill",
]

# 队员专属协作工具白名单（chap15 F6/N2）。
# 主 Agent 与普通 SubAgent 看不到这些工具，队员通过 teammate=True 获得。
TEAMMATE_EXTRA_TOOLS: list[str] = [
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "SendMessage",
]


# ── 辅助 ────────────────────────────────────────────────────────────────────

def is_mcp_or_skill(name: str) -> bool:
    """MCP 工具按命名约定（mcp__ 前缀）或 Skill 工具识别（本期按前缀即可）。

    spec F28 注：MCP 工具与 Skill 工具在后台模式下也允许通过。
    """
    return name.startswith("mcp__")


# ── FilterParams ────────────────────────────────────────────────────────────

@dataclass
class FilterParams:
    """工具过滤参数，对应 spec F30 每一步的输入。"""

    all: list[str]
    """registry 的全量工具名（按注册顺序）。"""

    source: int
    """子 Agent 来源整数值：0=builtin, 1=user, 2=project, 3=plugin（与 subagent.Source 对齐）。"""

    background: bool
    """是否为后台 Agent。"""

    allowed: list[str] = field(default_factory=list)
    """Agent 定义层 tools 白名单；空表示不收窄。"""

    disallowed: list[str] = field(default_factory=list)
    """Agent 定义层 disallowedTools 黑名单。"""

    teammate: bool = False
    """是否为 Team 队员（chap15 T17）。True 时注入 TEAMMATE_EXTRA_TOOLS。"""


# ── 核心过滤函数 ─────────────────────────────────────────────────────────────

def apply_agent_tool_filter(p: FilterParams) -> list[str]:
    """按 spec F30 顺序应用过滤，返回最终 allowed 工具名列表。

    过滤顺序：
    1. 起点 = p.all 副本
    2. 去掉 ALL_AGENT_DISALLOWED_TOOLS
    3. 若 p.source >= 1（非 builtin），去掉 CUSTOM_AGENT_DISALLOWED_TOOLS（本期为空）
    4. 若 p.background，与 ASYNC_AGENT_ALLOWED_TOOLS + MCP/Skill 命名约定取交集
    5. 去掉 p.disallowed
    6. 若 p.allowed 非空，与之取交集
    7. 若 p.teammate=True，追加 TEAMMATE_EXTRA_TOOLS（不受前面过滤限制）
    """
    result = list(p.all)

    # 步骤 1：去掉全局禁止列表
    disallowed_set = set(ALL_AGENT_DISALLOWED_TOOLS)
    result = [t for t in result if t not in disallowed_set]

    # 步骤 2：自定义来源额外禁用（本期 CUSTOM_AGENT_DISALLOWED_TOOLS 为空）
    if p.source >= 1 and CUSTOM_AGENT_DISALLOWED_TOOLS:
        custom_disallowed = set(CUSTOM_AGENT_DISALLOWED_TOOLS)
        result = [t for t in result if t not in custom_disallowed]

    # 步骤 3：后台白名单交集
    if p.background:
        async_allowed_set = set(ASYNC_AGENT_ALLOWED_TOOLS)
        result = [t for t in result if t in async_allowed_set or is_mcp_or_skill(t)]

    # 步骤 4：应用定义层黑名单
    if p.disallowed:
        def_disallowed_set = set(p.disallowed)
        result = [t for t in result if t not in def_disallowed_set]

    # 步骤 5：应用定义层白名单（非空才收窄）
    if p.allowed:
        def_allowed_set = set(p.allowed)
        result = [t for t in result if t in def_allowed_set]

    # 步骤 6（chap15 T17）：队员模式注入协作工具
    if p.teammate:
        result_set = set(result)
        for tool in TEAMMATE_EXTRA_TOOLS:
            if tool not in result_set:
                result.append(tool)

    # 无论 teammate 如何，非 teammate 时确保不含协作工具
    if not p.teammate:
        teammate_set = set(TEAMMATE_EXTRA_TOOLS)
        result = [t for t in result if t not in teammate_set]

    return result
