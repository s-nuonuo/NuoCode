"""prompt 包：模块化系统提示装配 + 环境采集 + 补充消息构造。

对外稳定接口：
- :func:`build_system_prompt`：装配稳定系统提示（可缓存）。
- :class:`Environment` / :func:`gather_environment`：环境段（不缓存）。
- :func:`system_reminder` / :func:`plan_reminder`：补充消息构造。
- :data:`EXECUTE_DIRECTIVE`：``/do`` 注入的用户消息文案。
- :func:`render_banner` / :data:`CAT_BANNER` / :data:`READY_HINT`：启动横幅。
"""

from __future__ import annotations

from nuocode.prompt.environment import Environment, gather_environment
from nuocode.prompt.modules import Module, fixed_modules, optional_modules
from nuocode.prompt.reminder import EXECUTE_DIRECTIVE, plan_reminder, system_reminder
from nuocode.prompt.skills_block import (
    ActiveSkillEntry,
    SkillCatalogItem,
    render_active_skills_block,
    render_skills_catalog,
)


def assemble_system(mods: list[Module]) -> str:
    """按 ``priority`` 升序稳定排序、跳过空 ``content``、以空行连接。"""
    ordered = sorted(mods, key=lambda m: m.priority)
    parts = [m.content for m in ordered if m.content]
    return "\n\n".join(parts)


def build_system_prompt(
    instructions: str = "", memory: str = "", skills_catalog: str = ""
) -> str:
    """装配完整稳定系统提示（七固定模块 + 三可选槽）。

    - ``instructions``：项目指令文件（nuocode.md）拼接后的文本，注入 priority 80。
    - ``skills_catalog``：chap11 Skill 第一阶段列表文本，注入 priority 90。
    - ``memory``：长期记忆索引文本，注入 priority 100。
    - 任一参数为空字符串时对应模块跳过（与 ch08 行为一致）。
    """
    return assemble_system(
        fixed_modules() + optional_modules(instructions, memory, skills_catalog)
    )


# ───────── 启动横幅（保留） ─────────

CAT_BANNER: str = r"""

(\_/)
(^.^)
(_(_)

""".lstrip("\n")

READY_HINT: str = (
    "Ready. Type your message and press Enter to send. "
    "(Alt+Enter for newline, type / to see commands)"
)


def render_banner(version: str, cwd: str) -> str:
    """启动横幅：ASCII 猫 + 应用名版本 + cwd + 就绪提示行。"""
    lines = [
        CAT_BANNER.rstrip(),
        "",
        f"  nuocode v{version}",
        f"  cwd: {cwd}",
        "",
        f"  {READY_HINT}",
    ]
    return "\n".join(lines)


__all__ = [
    "ActiveSkillEntry",
    "CAT_BANNER",
    "EXECUTE_DIRECTIVE",
    "Environment",
    "Module",
    "READY_HINT",
    "SkillCatalogItem",
    "assemble_system",
    "build_system_prompt",
    "fixed_modules",
    "gather_environment",
    "optional_modules",
    "plan_reminder",
    "render_active_skills_block",
    "render_banner",
    "render_skills_catalog",
    "system_reminder",
]
