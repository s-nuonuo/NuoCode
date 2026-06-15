"""补充消息（system-reminder）与规划模式提醒。

system-reminder 用 ``<system-reminder>`` 标签包裹，告知模型这是
系统补充上下文而非用户提问；该消息每轮动态构造、不写入持久历史。
"""

from __future__ import annotations

_PLAN_REMINDER_FULL: str = (
    "你当前处于「计划模式」（PLAN MODE）。\n"
    "- 仅可使用只读工具（read_file、glob、grep）调研代码库；\n"
    "  禁止写文件、编辑文件或执行 shell 命令。\n"
    "- 基于调研产出一份清晰、分步骤的执行计划：每步包含目标、涉及文件、关键操作；\n"
    "  必要时附带风险/回滚提示。\n"
    "- 计划写完即停下，等待用户用 /do 批准后再开始实际执行。\n"
    "- 这是系统补充指令，不要把它当成用户提问来直接回应或复述。"
)

_PLAN_REMINDER_CONCISE: str = "提醒：仍处于计划模式，仅可只读工具，写计划完即停下，等待 /do。"


def system_reminder(body: str) -> str:
    """用 ``<system-reminder>`` 标签包裹补充指令。"""
    return f"<system-reminder>\n{body}\n</system-reminder>"


def plan_reminder(full: bool) -> str:
    """规划模式提醒：full=完整版；否则精简版。"""
    return system_reminder(_PLAN_REMINDER_FULL if full else _PLAN_REMINDER_CONCISE)


EXECUTE_DIRECTIVE: str = "请按上面的计划开始执行。"


__all__ = [
    "EXECUTE_DIRECTIVE",
    "plan_reminder",
    "system_reminder",
]
