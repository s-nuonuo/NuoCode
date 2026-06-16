"""MCP 远端工具适配为 nuocode :class:`~nuocode.tool.Tool` 协议。

`adapt_tool` 把 SDK 返回的 `mcp.types.Tool` 包成 :class:`McpTool`；后者实现 nuocode
工具协议（`name()` / `description()` / `parameters()` / `read_only` / `execute`）。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Protocol

import mcp.types as mtypes

from nuocode.tool import Result

_VALID_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_non_text_warn_once: set[str] = set()


class CallerSession(Protocol):
    """最小协议形式：仅承接 ``call_tool``，便于单测注入 stub。"""

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None
    ) -> mtypes.CallToolResult: ...


@dataclass
class McpTool:
    """适配后的 MCP 工具。``name()`` 返回 ``mcp__<server>__<tool>``。"""

    full_name: str
    remote_name: str
    description_text: str
    parameters_schema: dict[str, Any]
    read_only: bool
    caller: CallerSession = field(repr=False)

    def name(self) -> str:
        return self.full_name

    def description(self) -> str:
        return self.description_text

    def parameters(self) -> dict[str, Any]:
        return self.parameters_schema

    async def execute(self, args: str) -> Result:
        """`args` 是 nuocode 标准的 JSON 字符串。失败/超时均转 ``is_error``。"""
        arg_map: dict[str, Any] | None
        try:
            parsed = json.loads(args) if args else None
        except json.JSONDecodeError as e:
            return Result(content=f"MCP 工具参数解析失败: {e}", is_error=True)
        if isinstance(parsed, dict) and parsed:
            arg_map = parsed
        else:
            arg_map = None

        try:
            result = await asyncio.wait_for(
                self.caller.call_tool(self.remote_name, arg_map),
                timeout=30,
            )
        except TimeoutError:
            return Result(content="MCP 工具调用超时 (30s)", is_error=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            return Result(content=f"MCP 工具调用失败: {e}", is_error=True)

        texts: list[str] = []
        saw_non_text = False
        for block in result.content or []:
            if isinstance(block, mtypes.TextContent):
                texts.append(block.text)
            else:
                saw_non_text = True
        if saw_non_text and self.full_name not in _non_text_warn_once:
            _non_text_warn_once.add(self.full_name)
            print(
                f"[mcp] warn: tool {self.full_name} returned non-text content blocks (dropped)",
                file=sys.stderr,
            )

        return Result(
            content="\n".join(texts),
            is_error=bool(getattr(result, "isError", False)),
        )


def adapt_tool(server_name: str, t: mtypes.Tool, session: CallerSession) -> McpTool | None:
    """把远端 ``mcp.types.Tool`` 适配为 :class:`McpTool`；非法名返回 ``None``。"""
    full_name = f"mcp__{server_name}__{t.name}"
    if not _VALID_NAME.fullmatch(full_name):
        print(
            f"[mcp] warn: skip tool {full_name}: name contains illegal characters",
            file=sys.stderr,
        )
        return None

    desc = t.description or f"来自 MCP server {server_name} 的工具 {t.name}"

    raw_schema = getattr(t, "inputSchema", None)
    if raw_schema and isinstance(raw_schema, dict):
        params: dict[str, Any] = dict(raw_schema)
    else:
        params = {"type": "object"}

    annotations = getattr(t, "annotations", None)
    read_only = bool(annotations and getattr(annotations, "readOnlyHint", False))

    return McpTool(
        full_name=full_name,
        remote_name=t.name,
        description_text=desc,
        parameters_schema=params,
        read_only=read_only,
        caller=session,
    )


__all__ = [
    "CallerSession",
    "McpTool",
    "adapt_tool",
]
