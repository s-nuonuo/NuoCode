"""工具系统：抽象、注册中心、6 个核心工具。

所有工具失败永远以 :class:`Result` (``is_error=True``) 返回，绝不向上层抛异常。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from nuocode.llm import ToolDefinition

DEFAULT_TIMEOUT: float = 30.0
"""单个工具执行的默认超时（秒），N1。"""


@dataclass
class Result:
    """工具执行结果。"""

    content: str
    is_error: bool = False


@runtime_checkable
class Tool(Protocol):
    """统一工具抽象（F1）。

    ``read_only``：True 表示只读工具（可并发执行 & Plan Mode 放行）。
    ``is_system``：chap11 系统工具标记（不受 allowed_tools 约束）。
    """

    read_only: bool
    is_system: bool

    def name(self) -> str: ...

    def description(self) -> str: ...

    def parameters(self) -> dict[str, Any]: ...

    async def execute(self, args: str) -> Result: ...


def _truncate(s: str, max_lines: int, max_chars: int) -> str:
    """超出 ``max_lines`` 或 ``max_chars`` 时尾部追加 ``\\n[truncated]``。"""
    truncated = False
    if len(s) > max_chars:
        s = s[:max_chars]
        truncated = True
    if max_lines > 0:
        lines = s.splitlines()
        if len(lines) > max_lines:
            s = "\n".join(lines[:max_lines])
            truncated = True
    if truncated:
        s += "\n[truncated]"
    return s


class Registry:
    """工具注册中心：按序登记、按名查找、导出定义、带超时执行。"""

    def __init__(self) -> None:
        self._order: list[str] = []
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        n = tool.name()
        if n in self._tools:
            raise ValueError(f"工具 {n!r} 已注册")
        self._order.append(n)
        self._tools[n] = tool

    def register_skill_tool(self, tool: Tool) -> None:
        """chap11：Skill 专属工具动态注册，重复名静默覆盖。"""
        n = tool.name()
        if n not in self._tools:
            self._order.append(n)
        self._tools[n] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._order)

    def count(self) -> int:
        """已注册工具数量（chap10 /status 用）。"""
        return len(self._order)

    def definitions(self) -> list[ToolDefinition]:
        """按注册顺序导出 ToolDefinition 列表（F3/AC1）。"""
        return [
            ToolDefinition(
                name=n,
                description=self._tools[n].description(),
                input_schema=self._tools[n].parameters(),
            )
            for n in self._order
        ]

    def read_only_definitions(self) -> list[ToolDefinition]:
        """Plan Mode：只导出 read_only==True 的工具定义，保留注册顺序。"""
        return [
            ToolDefinition(
                name=n,
                description=self._tools[n].description(),
                input_schema=self._tools[n].parameters(),
            )
            for n in self._order
            if getattr(self._tools[n], "read_only", False)
        ]

    def is_read_only(self, name: str) -> bool:
        """分批判定；未知工具返回 False（按串行处理）。"""
        t = self._tools.get(name)
        return t is not None and bool(getattr(t, "read_only", False))

    def is_system(self, name: str) -> bool:
        """chap11：系统工具判定。"""
        t = self._tools.get(name)
        return t is not None and bool(getattr(t, "is_system", False))

    def definitions_filtered(self, allowed: list[str]) -> list[ToolDefinition]:
        """chap11：按白名单 + 系统工具豁免导出定义。

        allowed 为空列表时仅导出系统工具。
        """
        allowset = set(allowed or [])
        out: list[ToolDefinition] = []
        for n in self._order:
            t = self._tools[n]
            if n in allowset or bool(getattr(t, "is_system", False)):
                out.append(
                    ToolDefinition(
                        name=n,
                        description=t.description(),
                        input_schema=t.parameters(),
                    )
                )
        return out

    async def execute(self, name: str, args: str, timeout: float = DEFAULT_TIMEOUT) -> Result:
        tool = self._tools.get(name)
        if tool is None:
            return Result(content=f"未知工具: {name}", is_error=True)
        try:
            return await asyncio.wait_for(tool.execute(args or "{}"), timeout=timeout)
        except TimeoutError:
            return Result(content=f"工具 {name} 执行超时（{timeout}s）", is_error=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            return Result(content=f"工具 {name} 异常: {e}", is_error=True)


def new_default_registry() -> Registry:
    """构造并注册 6 个默认工具。"""
    from nuocode.tool.bash import BashTool
    from nuocode.tool.edit_file import EditFileTool
    from nuocode.tool.glob_tool import GlobTool
    from nuocode.tool.grep_tool import GrepTool
    from nuocode.tool.read_file import ReadFileTool
    from nuocode.tool.write_file import WriteFileTool

    reg = Registry()
    reg.register(ReadFileTool())
    reg.register(WriteFileTool())
    reg.register(EditFileTool())
    reg.register(BashTool())
    reg.register(GlobTool())
    reg.register(GrepTool())
    return reg


__all__ = [
    "DEFAULT_TIMEOUT",
    "Registry",
    "Result",
    "Tool",
    "_truncate",
    "new_default_registry",
]
