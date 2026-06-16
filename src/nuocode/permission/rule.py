"""权限规则与匹配（F3）。

规则形如 `Tool(pattern)` 或 `Tool`：
- 工具名为友好名（Bash/Read/Write/Edit/Glob/Grep）。
- pattern 段支持 glob：`*` 任意串；`**` 文件路径跨目录段（命令串等价 `*`）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from nuocode.permission import Decision


@dataclass
class Rule:
    tool: str  # 友好名
    pattern: str  # "" = 该工具全部调用
    allow: bool  # True=allow, False=deny


@dataclass
class RuleSet:
    allow: list[Rule] = field(default_factory=list)
    deny: list[Rule] = field(default_factory=list)

    def match(self, friendly: str, target: str) -> tuple[Decision, bool]:
        """先 deny 后 allow；返回 (裁决, 命中?)；未命中则 (ALLOW, False)。"""
        for r in self.deny:
            if r.tool == friendly and match_pattern(r.pattern, target):
                return (Decision.DENY, True)
        for r in self.allow:
            if r.tool == friendly and match_pattern(r.pattern, target):
                return (Decision.ALLOW, True)
        return (Decision.ALLOW, False)


def parse_rule(s: str) -> tuple[Rule, bool]:
    """解析 `Tool(pattern)` 或 `Tool`；非法返回 (Rule("","",False), False)。"""
    if not s or not isinstance(s, str):
        return (Rule("", "", False), False)
    s = s.strip()
    if not s:
        return (Rule("", "", False), False)
    if "(" not in s:
        # `Tool` —— 全匹配
        if not s.isidentifier() and not s.isalpha():
            # 限制为字母名（友好名都是字母）
            pass
        return (Rule(tool=s, pattern="", allow=False), True)
    if not s.endswith(")"):
        return (Rule("", "", False), False)
    lparen = s.index("(")
    tool = s[:lparen].strip()
    pattern = s[lparen + 1 : -1]
    if not tool:
        return (Rule("", "", False), False)
    return (Rule(tool=tool, pattern=pattern, allow=False), True)


def _glob_to_regex_command(pattern: str) -> str:
    """命令 glob：`*` 与 `**` 都匹配任意字符（含空格、含 `/`）。"""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            # 吞掉连续的 *
            while i < len(pattern) and pattern[i] == "*":
                i += 1
            out.append(".*")
            continue
        if c == "?":
            out.append(".")
        else:
            out.append(re.escape(c))
        i += 1
    return "^" + "".join(out) + "$"


def _glob_to_regex_path(pattern: str) -> str:
    """文件路径 glob：`*` 段内任意（不含 `/`）；`**` 跨目录段（含 `/`）。"""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                # **
                # 吞 ** 及其后可能的 /
                i += 2
                if i < len(pattern) and pattern[i] == "/":
                    out.append("(?:.*/)?")
                    i += 1
                else:
                    out.append(".*")
                continue
            else:
                out.append("[^/]*")
                i += 1
                continue
        if c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return "^" + "".join(out) + "$"


def match_pattern(pattern: str, target: str) -> bool:
    """空 pattern 恒匹配。`target` 含 `/` 视为路径，否则视为命令串。"""
    if pattern == "":
        return True
    target = target or ""
    if "/" in target or "/" in pattern.replace("**", "").replace("*", ""):
        regex = _glob_to_regex_path(pattern)
    else:
        regex = _glob_to_regex_command(pattern)
    try:
        return re.fullmatch(regex, target) is not None
    except re.error:
        return False


__all__ = ["Rule", "RuleSet", "match_pattern", "parse_rule"]
