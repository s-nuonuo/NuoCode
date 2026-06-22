"""slash 命令体系：注册中心 + 12 条内置命令 + UI 抽象层。"""

from __future__ import annotations

from nuocode.command.builtins import REVIEW_DIRECTIVE, register_builtins
from nuocode.command.command import Command, Handler, Kind
from nuocode.command.dispatch import parse
from nuocode.command.registry import Registry
from nuocode.command.ui import UI, NopUI

__all__ = [
    "REVIEW_DIRECTIVE",
    "Command",
    "Handler",
    "Kind",
    "NopUI",
    "Registry",
    "UI",
    "parse",
    "register_builtins",
]
