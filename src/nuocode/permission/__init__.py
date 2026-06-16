"""权限模块（chap06）：五层防御的前四层 + 配置加载 + 规则持久化。

对外暴露：`Mode`/`Decision`/`Category`/`Outcome`/`Engine`/`new_engine`/`SettingsError`。
"""

from __future__ import annotations

from enum import IntEnum


class Mode(IntEnum):
    """权限模式（四档）。"""

    DEFAULT = 0  # 只读 Allow / 文件写 Ask / 命令执行 Ask
    ACCEPT_EDITS = 1  # 文件写 Allow / 命令执行 Ask
    PLAN = 2  # 仅只读工具可见（沿用 ch04），矩阵作防御兜底
    BYPASS = 3  # 全 Allow（黑名单/沙箱仍拦）

    def __str__(self) -> str:
        return _MODE_NAMES[self.value]


_MODE_NAMES = {
    Mode.DEFAULT.value: "default",
    Mode.ACCEPT_EDITS.value: "acceptEdits",
    Mode.PLAN.value: "plan",
    Mode.BYPASS.value: "bypassPermissions",
}

_MODE_LOOKUP = {
    "default": Mode.DEFAULT,
    "acceptedits": Mode.ACCEPT_EDITS,
    "accept_edits": Mode.ACCEPT_EDITS,
    "plan": Mode.PLAN,
    "bypasspermissions": Mode.BYPASS,
    "bypass": Mode.BYPASS,
}


def parse_mode(s: str) -> tuple[Mode, bool]:
    """大小写不敏感识别四档名；未知返回 (Mode.DEFAULT, False)。"""
    if not s:
        return (Mode.DEFAULT, False)
    key = s.strip().lower()
    if key in _MODE_LOOKUP:
        return (_MODE_LOOKUP[key], True)
    return (Mode.DEFAULT, False)


class Decision(IntEnum):
    ALLOW = 0
    DENY = 1
    ASK = 2


class Category(IntEnum):
    READ = 0
    WRITE = 1
    EXEC = 2


class Outcome(IntEnum):
    """人在回路三选一。"""

    DENY_ONCE = 0  # 拒绝本次
    ALLOW_ONCE = 1  # 允许本次（不留规则）
    ALLOW_FOREVER = 2  # 永久允许（写本地层文件，精确匹配）


class SettingsError(Exception):
    """配置文件解析错误（调用方降级，不向上抛致命）。"""


# 延迟导入 Engine，避免循环。
from nuocode.permission.engine import Engine, new_engine  # noqa: E402

__all__ = [
    "Category",
    "Decision",
    "Engine",
    "Mode",
    "Outcome",
    "SettingsError",
    "new_engine",
    "parse_mode",
]
