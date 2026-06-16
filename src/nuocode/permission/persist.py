"""永久放行规则生成（精确匹配，不自动泛化）。"""

from __future__ import annotations

import re
from pathlib import Path

from nuocode.llm import ToolCall
from nuocode.permission.rule import Rule
from nuocode.permission.settings import extract_target, friendly_name


def _escape_glob(s: str) -> str:
    """转义 glob 元字符（`*`/`?`/`[`/`]`），让规则严格匹配字面命令。"""
    return re.sub(r"([*?\[\]])", r"[\1]", s)


def rule_for(call: ToolCall, root: str) -> tuple[Rule, str, bool]:
    """据一次工具调用生成精确规则。返回 (Rule, yaml串, ok)。"""
    target, is_file, ok = extract_target(call)
    if not ok:
        return (Rule("", "", False), "", False)
    fname = friendly_name(call.name)
    if is_file:
        # 文件类：转项目相对 slash 路径
        p = Path(target)
        if not p.is_absolute():
            p = Path(root) / p
        try:
            rel = p.resolve(strict=False).relative_to(Path(root))
            rel_s = str(rel).replace("\\", "/")
        except (ValueError, OSError):
            rel_s = str(p).replace("\\", "/")
        pattern = _escape_glob(rel_s)
    else:
        # 命令类：转义 glob
        pattern = _escape_glob(target)
    rule = Rule(tool=fname, pattern=pattern, allow=True)
    rule_str = f"{fname}({pattern})"
    return (rule, rule_str, True)


__all__ = ["rule_for"]
