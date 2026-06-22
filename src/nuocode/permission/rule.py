"""权限规则与匹配（chap12 升级版）。

规则形如 ``Tool(pattern)`` 或 ``Tool``：
- 工具名为友好名（Bash/Read/Write/Edit/Glob/Grep）。
- pattern 段支持四种匹配语法（见 matcher.py）：
  - ``=value``  精确匹配
  - ``~regex``  正则匹配
  - ``!inner``  对 inner 取反
  - ``value``   无前缀 → glob（向后兼容）

向后兼容：现有 ``Bash(git *)`` 写法继续工作，解析为 GlobMatcher。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nuocode.permission import Decision
from nuocode.permission.matcher import Matcher, GlobMatcher, compile_matcher

if TYPE_CHECKING:
    pass


@dataclass
class Rule:
    tool: str                    # 友好名
    matcher: Matcher | None      # None = 该工具全匹配；替换原 pattern 字符串
    allow: bool                  # True=allow, False=deny
    raw: str = ""                # 原始 pattern 串，供日志 / 调试使用
    # 向后兼容：暴露 .pattern 属性
    @property
    def pattern(self) -> str:
        """向后兼容属性：返回 raw（原始 pattern 串）。"""
        return self.raw


@dataclass
class RuleSet:
    allow: list[Rule] = field(default_factory=list)
    deny: list[Rule] = field(default_factory=list)

    def match(self, friendly: str, target: str) -> tuple[Decision, bool]:
        """先 deny 后 allow；返回 (裁决, 命中?)；未命中则 (ALLOW, False)。"""
        for r in self.deny:
            if r.tool == friendly and match_rule(r, target):
                return (Decision.DENY, True)
        for r in self.allow:
            if r.tool == friendly and match_rule(r, target):
                return (Decision.ALLOW, True)
        return (Decision.ALLOW, False)


def match_rule(r: Rule, target: str) -> bool:
    """用 Rule 中的 matcher 匹配 target。None matcher 表示全匹配。"""
    if r.matcher is None:
        return True
    return r.matcher.match(target)


def parse_rule(s: str) -> tuple[Rule | None, str | None]:
    """解析 ``Tool(pattern)`` 或 ``Tool``。

    返回 ``(Rule, None)`` 或 ``(None, error_message)``。
    失败时不抛异常，由调用方决定如何处理错误（通常打 stderr 后跳过）。
    """
    if not s or not isinstance(s, str):
        return (None, "empty or non-string rule")
    s = s.strip()
    if not s:
        return (None, "empty rule string")
    if "(" not in s:
        # ``Tool`` —— 全匹配
        return (Rule(tool=s, matcher=None, allow=False, raw=""), None)
    if not s.endswith(")"):
        return (None, f"missing closing ')' in rule {s!r}")
    lparen = s.index("(")
    tool = s[:lparen].strip()
    pattern = s[lparen + 1 : -1]
    if not tool:
        return (None, f"empty tool name in rule {s!r}")
    if pattern == "":
        # 空 pattern → 全匹配
        return (Rule(tool=tool, matcher=None, allow=False, raw=""), None)
    # 编译 matcher：Bash 工具使用 is_command=True（整串通配）
    try:
        m = compile_matcher(pattern, is_command=(tool == "Bash"))
    except ValueError as e:
        return (None, str(e))
    return (Rule(tool=tool, matcher=m, allow=False, raw=pattern), None)


# ────────── 向后兼容：保留 match_pattern（供现有测试直接调用）──────────

def _glob_to_regex_command(pattern: str) -> str:
    """命令 glob：``*`` 与 ``**`` 都匹配任意字符（含空格、含 ``/``）。"""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
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
    """文件路径 glob：``*`` 段内任意（不含 ``/``）；``**`` 跨目录段（含 ``/``）。"""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
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
    """向后兼容函数：空 pattern 恒匹配。``target`` 含 ``/`` 视为路径，否则命令串。"""
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


__all__ = ["Rule", "RuleSet", "match_pattern", "match_rule", "parse_rule"]
