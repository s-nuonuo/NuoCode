"""通过 importlib.resources 读取内置 Agent 定义文件（chap13）。

``builtin_definitions()`` 返回随包发布的 3 个内置角色定义（general-purpose / Explore / Plan）。

spec F5（内置级加载）、F7（内置解析失败立即 raise）。
"""

from __future__ import annotations

from importlib.resources import files

from nuocode.subagent.definition import Definition, Source
from nuocode.subagent.parser import parse_definition


def builtin_definitions() -> list[Definition]:
    """读取 nuocode/subagent/builtin/*.md，返回按 name 升序的内置定义列表。

    内置文件解析失败时立即 raise（属于代码 bug，启动期须 fail-fast）。
    """
    pkg = files("nuocode.subagent.builtin")
    defs: list[Definition] = []
    for entry in pkg.iterdir():
        if not entry.name.endswith(".md"):
            continue
        data = entry.read_bytes()
        # file_path 标注为 "builtin:<filename>" 以便调试
        d = parse_definition(data, f"builtin:{entry.name}", Source.BUILTIN)
        defs.append(d)
    defs.sort(key=lambda d: d.name.lower())
    return defs
