"""prompt 包单测：模块装配、环境采集、补充消息构造。"""

from __future__ import annotations

import os
import tempfile

from nuocode.prompt import (
    Environment,
    Module,
    assemble_system,
    build_system_prompt,
    fixed_modules,
    gather_environment,
    optional_modules,
    plan_reminder,
    system_reminder,
)

# ───────── 装配 ─────────


def test_assemble_order_by_priority() -> None:
    mods = [
        Module(name="b", priority=20, content="B"),
        Module(name="a", priority=10, content="A"),
        Module(name="c", priority=30, content="C"),
    ]
    assert assemble_system(mods) == "A\n\nB\n\nC"


def test_assemble_skips_empty_content() -> None:
    mods = [
        Module(name="a", priority=10, content="A"),
        Module(name="empty", priority=20, content=""),
        Module(name="c", priority=30, content="C"),
    ]
    out = assemble_system(mods)
    # 空模块不出现、不产生连续多空行
    assert out == "A\n\nC"
    assert "\n\n\n" not in out


def test_build_system_prompt_identity_before_tool_usage() -> None:
    text = build_system_prompt()
    # 身份段在工具使用段之前（按七固定模块顺序）
    assert text.index("nuocode") < text.index("工具使用准则")
    # 模块以空行分隔
    assert "\n\n" in text


def test_build_system_prompt_skips_optional_slots() -> None:
    """三空槽默认 content 为空，装配后不产生连续多空行。"""
    text = build_system_prompt()
    assert "\n\n\n" not in text


def test_build_system_prompt_extensible() -> None:
    """挂载即扩展：新增模块按优先级落到正确位置。"""
    extra = Module(name="extra", priority=15, content="EXTRA-MODULE-X")
    text = assemble_system(fixed_modules() + [extra] + optional_modules())
    # 落在身份(10)和系统约束(20)之间
    idx_identity = text.index("nuocode")
    idx_extra = text.index("EXTRA-MODULE-X")
    idx_constraints = text.index("系统约束")
    assert idx_identity < idx_extra < idx_constraints


def test_build_system_prompt_deterministic() -> None:
    """N1 确定性：连续两次构造结果逐字节相等。"""
    assert build_system_prompt() == build_system_prompt()


def test_dual_reinforcement_in_system() -> None:
    """F5 双重强化：系统提示含「编辑前先读」与「优先用专用工具」语义。"""
    text = build_system_prompt()
    # 编辑前先读
    assert "编辑" in text and "read_file" in text
    # 优先用专用工具
    assert "优先" in text
    for name in ("read_file", "glob", "grep"):
        assert name in text


# ───────── 环境 ─────────


def test_gather_environment_basic() -> None:
    env = gather_environment("dev", "test-model")
    assert env.version == "dev"
    assert env.model == "test-model"
    assert env.platform  # 至少有平台
    assert env.date  # 日期存在
    assert env.working_dir  # cwd 应可获得


def test_gather_environment_non_git_dir() -> None:
    """非 git 目录：git_status 留空，不抛异常。"""
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        try:
            os.chdir(td)
            env = gather_environment("dev", "m")
            assert env.git_status == ""
            assert env.working_dir
        finally:
            os.chdir(cwd)


def test_environment_render_omits_empty_fields() -> None:
    env = Environment(working_dir="/tmp", platform="linux", date="2026-01-01")
    text = env.render()
    assert "工作目录: /tmp" in text
    assert "平台: linux" in text
    assert "日期: 2026-01-01" in text
    # 空字段不出现
    assert "Git 状态" not in text
    assert "应用版本" not in text
    assert "当前模型" not in text


def test_environment_changes_do_not_affect_stable() -> None:
    """N1：环境信息变化不应改变稳定系统提示。"""
    stable = build_system_prompt()
    # 稳定块不应含动态内容（cwd/date/git）
    assert os.getcwd() not in stable
    import datetime as _dt

    assert _dt.date.today().isoformat() not in stable


# ───────── 补充消息 ─────────


def test_system_reminder_wraps_with_tag() -> None:
    out = system_reminder("HELLO")
    assert out.startswith("<system-reminder>")
    assert out.endswith("</system-reminder>")
    assert "HELLO" in out


def test_plan_reminder_full_vs_concise() -> None:
    full = plan_reminder(True)
    concise = plan_reminder(False)
    assert "<system-reminder>" in full and "<system-reminder>" in concise
    # 完整版至少应含若干关键信息
    assert "计划模式" in full
    assert "只读" in full
    assert "/do" in full
    # 精简版更短
    assert len(concise) < len(full)


# ───────── chap09: build_system_prompt 参数化 ─────────


def test_build_system_prompt_with_instructions_and_memory() -> None:
    text = build_system_prompt("CUSTOM_RULE_X", "MEMORY_INDEX_Y")
    assert "CUSTOM_RULE_X" in text
    assert "MEMORY_INDEX_Y" in text
    # custom-instructions(80) 在 long-term-memory(100) 前
    assert text.index("CUSTOM_RULE_X") < text.index("MEMORY_INDEX_Y")


def test_build_system_prompt_empty_args_compatible() -> None:
    """空字符串 → 与 ch08 默认行为一致（不出现空模块）。"""
    text = build_system_prompt("", "")
    assert "\n\n\n" not in text
    # 与无参调用结果一致
    assert text == build_system_prompt()


def test_optional_modules_skips_empty_slot() -> None:
    mods = optional_modules("", "MEM")
    contents = {m.name: m.content for m in mods}
    assert contents["custom_instructions"] == ""
    assert contents["long_term_memory"] == "MEM"
