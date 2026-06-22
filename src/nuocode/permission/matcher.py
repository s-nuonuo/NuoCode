"""permission.Matcher: 四种结构化匹配类型（chap12）。

前缀语法：
  ``=value``  → ExactMatcher   整串相等
  ``~regex``  → RegexMatcher   正则搜索
  ``!inner``  → NotMatcher     对 inner 取反，inner 仍按规则解析
  ``value``   → GlobMatcher    无前缀，沿用 glob 语义

GlobMatcher 语义与 ``is_command`` 参数：
  - ``is_command=True``  : ``*`` / ``**`` 均匹配任意字符（含空格、含 ``/``），
    适用于 Bash 工具的命令字符串。
  - ``is_command=False`` : ``*`` 匹配段内任意（不含 ``/``），``**`` 跨目录；
    适用于文件路径匹配。

向后兼容：旧的 ``Bash(git *)`` 写法等价于无前缀 GlobMatcher(is_command=True)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class Matcher(Protocol):
    """匹配统一接口。四种实现:
    ``ExactMatcher`` / ``GlobMatcher`` / ``RegexMatcher`` / ``NotMatcher``。
    """

    def match(self, s: str) -> bool: ...

    def __str__(self) -> str: ...


# ────────── 内部 glob 实现（内联，避免循环导入）──────────

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
    """文件路径 glob：``*`` 段内任意（不含 ``/``）；``**`` 跨目录。"""
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


def _match_glob(pattern: str, target: str, is_command: bool) -> bool:
    """通用 glob 匹配入口。"""
    if pattern == "":
        return True
    target = target or ""
    if is_command:
        regex = _glob_to_regex_command(pattern)
    else:
        # 路径 glob：根据 target / pattern 是否含 / 决定策略
        if "/" in target or "/" in pattern.replace("**", "").replace("*", ""):
            regex = _glob_to_regex_path(pattern)
        else:
            regex = _glob_to_regex_command(pattern)
    try:
        return re.fullmatch(regex, target) is not None
    except re.error:
        return False


# ────────── 四种实现 ──────────

@dataclass(frozen=True)
class ExactMatcher:
    """整串相等匹配（前缀 ``=``）。"""

    value: str

    def match(self, s: str) -> bool:
        return s == self.value

    def __str__(self) -> str:
        return f"={self.value}"


@dataclass(frozen=True)
class GlobMatcher:
    """Glob 匹配（无前缀）。``is_command`` 决定 ``*`` 的跨 ``/`` 行为。"""

    pattern: str
    is_command: bool

    def match(self, s: str) -> bool:
        return _match_glob(self.pattern, s, self.is_command)

    def __str__(self) -> str:
        return self.pattern


@dataclass(frozen=True)
class RegexMatcher:
    """正则搜索匹配（前缀 ``~``）。"""

    src: str
    compiled: re.Pattern[str]

    def match(self, s: str) -> bool:
        return self.compiled.search(s) is not None

    def __str__(self) -> str:
        return f"~{self.src}"


@dataclass(frozen=True)
class NotMatcher:
    """对任意 Matcher 取反（前缀 ``!``）。支持嵌套：``!=value``、``!~regex``、``!glob``。"""

    inner: Matcher

    def match(self, s: str) -> bool:
        return not self.inner.match(s)

    def __str__(self) -> str:
        return f"!{self.inner}"


# ────────── 工厂 ──────────

def compile_matcher(pattern: str, *, is_command: bool) -> Matcher:
    """解析单条匹配描述串，返回 Matcher。失败抛 ``ValueError``。

    规则：
    - ``""``       → ValueError（空串无意义）
    - ``"=value"`` → ExactMatcher
    - ``"~regex"`` → RegexMatcher（regex 编译失败抛 ValueError）
    - ``"!inner"`` → NotMatcher(compile_matcher(inner, ...))
    - 其它         → GlobMatcher(pattern, is_command)
    """
    if not pattern:
        raise ValueError("empty matcher pattern")
    head, rest = pattern[0], pattern[1:]
    if head == "=":
        return ExactMatcher(rest)
    if head == "~":
        try:
            return RegexMatcher(rest, re.compile(rest))
        except re.error as e:
            raise ValueError(f"invalid regex {pattern!r}: {e}") from e
    if head == "!":
        inner = compile_matcher(rest, is_command=is_command)
        return NotMatcher(inner)
    return GlobMatcher(pattern, is_command)


__all__ = [
    "Matcher",
    "ExactMatcher",
    "GlobMatcher",
    "RegexMatcher",
    "NotMatcher",
    "compile_matcher",
]
