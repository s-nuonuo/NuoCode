"""危险命令黑名单（启发式、非完备、不可配置放开，N1）。

模块级编译好的 `re.Pattern` 列表，匹配命令串；任一命中即判 Deny。
本模块**不暴露任何加载/扩展接口**——黑名单是流水线最高优先级，
不存在配置项、规则或模式（含 `bypassPermissions`）能放开命中的命令。
"""

from __future__ import annotations

import re

# 启发式高危模式集合：覆盖已知危险命令骨架，**不追求穷尽**。
_BLACKLIST: list[re.Pattern[str]] = [
    # rm -rf 根 / 家目录 / 通配根
    re.compile(r"\brm\s+(-[a-zA-Z]*[rRfF][a-zA-Z]*\s+)+(/|~|\$HOME|/\*)"),
    re.compile(r"\brm\s+(-[a-zA-Z]*[rRfF][a-zA-Z]*\s+)+(/|~|\$HOME)\s*$"),
    # dd 写块设备
    re.compile(r"\bdd\b.*\bof=/dev/"),
    # fork bomb
    re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
    # mkfs.*
    re.compile(r"\bmkfs\."),
    # 重定向覆盖磁盘设备
    re.compile(r">\s*/dev/(sd|hd|nvme|disk)"),
    # chmod -R 777 根
    re.compile(r"\bchmod\s+-R\s+0?777\s+/"),
    # shutdown / reboot / halt（通常在 agent 场景应被禁）
    re.compile(r"\b(shutdown|reboot|halt|poweroff)\b\s+(-|now)"),
]


def hits_blacklist(command: str) -> bool:
    """命令串命中任意黑名单模式即返回 True。"""
    if not command:
        return False
    return any(p.search(command) for p in _BLACKLIST)


__all__ = ["hits_blacklist"]
