"""tests for nuocode.mcp.tool: 命名 / 字段适配 / execute 各分支。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import mcp.types as mtypes
import pytest

from nuocode.mcp import tool as mcp_tool
from nuocode.mcp.tool import McpTool, adapt_tool


class StubSession:
    def __init__(
        self, *, result: Any = None, exc: BaseException | None = None, block: bool = False
    ) -> None:
        self.result = result
        self.exc = exc
        self.block = block
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any] | None) -> mtypes.CallToolResult:
        self.calls.append((name, arguments))
        if self.block:
            await asyncio.Event().wait()
        if self.exc is not None:
            raise self.exc
        return self.result


def _make_remote_tool(
    name: str = "echo",
    *,
    desc: str | None = "echo a message",
    schema: dict[str, Any] | None = None,
    read_only: bool | None = None,
) -> mtypes.Tool:
    annotations = None
    if read_only is not None:
        annotations = mtypes.ToolAnnotations(readOnlyHint=read_only)
    return mtypes.Tool(
        name=name,
        description=desc,
        inputSchema=schema if schema is not None else {"type": "object"},
        annotations=annotations,
    )


# ───────────── adapt_tool ─────────────


def test_adapt_tool_full_name() -> None:
    t = _make_remote_tool()
    a = adapt_tool("github", t, StubSession())
    assert a is not None
    assert a.name() == "mcp__github__echo"
    assert a.remote_name == "echo"


def test_adapt_tool_illegal_chars(capsys: pytest.CaptureFixture[str]) -> None:
    t = _make_remote_tool(name="ec.ho")
    a = adapt_tool("github", t, StubSession())
    assert a is None
    assert "illegal characters" in capsys.readouterr().err


def test_adapt_tool_illegal_server_name(capsys: pytest.CaptureFixture[str]) -> None:
    t = _make_remote_tool()
    a = adapt_tool("git.hub", t, StubSession())
    assert a is None
    assert "illegal characters" in capsys.readouterr().err


def test_adapt_tool_description_default() -> None:
    t = _make_remote_tool(desc=None)
    a = adapt_tool("svr", t, StubSession())
    assert a is not None
    assert "MCP server svr" in a.description()


def test_adapt_tool_schema_passthrough() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    t = _make_remote_tool(schema=schema)
    a = adapt_tool("svr", t, StubSession())
    assert a is not None
    assert a.parameters() == schema
    assert a.parameters() is not schema  # 浅拷贝


def test_adapt_tool_empty_schema_fallback() -> None:
    t = _make_remote_tool(schema={})
    a = adapt_tool("svr", t, StubSession())
    assert a is not None
    assert a.parameters() == {"type": "object"}


def test_adapt_tool_read_only_true() -> None:
    t = _make_remote_tool(read_only=True)
    a = adapt_tool("svr", t, StubSession())
    assert a is not None
    assert a.read_only is True


def test_adapt_tool_read_only_false_or_missing() -> None:
    t = _make_remote_tool(read_only=False)
    a = adapt_tool("svr", t, StubSession())
    assert a is not None
    assert a.read_only is False

    t2 = _make_remote_tool(read_only=None)  # annotations is None
    a2 = adapt_tool("svr", t2, StubSession())
    assert a2 is not None
    assert a2.read_only is False


# ───────────── execute ─────────────


def _result_with_blocks(blocks: list[Any], *, is_error: bool = False) -> mtypes.CallToolResult:
    return mtypes.CallToolResult(content=blocks, isError=is_error)


def _new_tool(session: StubSession, name: str = "demo") -> McpTool:
    rt = _make_remote_tool(name=name)
    a = adapt_tool("svr", rt, session)
    assert a is not None
    return a


async def test_execute_success_concat_text() -> None:
    session = StubSession(
        result=_result_with_blocks(
            [
                mtypes.TextContent(type="text", text="hello"),
                mtypes.TextContent(type="text", text="world"),
            ]
        )
    )
    tool = _new_tool(session, name="ok1")
    r = await tool.execute(json.dumps({"a": 1}))
    assert r.is_error is False
    assert r.content == "hello\nworld"
    assert session.calls == [("ok1", {"a": 1})]


async def test_execute_empty_args() -> None:
    session = StubSession(
        result=_result_with_blocks(
            [
                mtypes.TextContent(type="text", text="ok"),
            ]
        )
    )
    tool = _new_tool(session, name="ok2")
    await tool.execute("")
    assert session.calls == [("ok2", None)]
    await tool.execute("{}")
    assert session.calls[-1] == ("ok2", None)


async def test_execute_remote_is_error_mapped() -> None:
    session = StubSession(
        result=_result_with_blocks([mtypes.TextContent(type="text", text="boom")], is_error=True)
    )
    tool = _new_tool(session, name="er1")
    r = await tool.execute("{}")
    assert r.is_error is True
    assert r.content == "boom"


async def test_execute_protocol_error_to_is_error() -> None:
    session = StubSession(exc=RuntimeError("conn dropped"))
    tool = _new_tool(session, name="er2")
    r = await tool.execute("{}")
    assert r.is_error is True
    assert "MCP 工具调用失败" in r.content
    assert "conn dropped" in r.content


async def test_execute_timeout_to_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session = StubSession(block=True)
    tool = _new_tool(session, name="er3")

    real_wait_for = asyncio.wait_for

    async def fast_wait_for(coro: Any, timeout: Any) -> Any:
        return await real_wait_for(coro, timeout=0.05)

    monkeypatch.setattr(asyncio, "wait_for", fast_wait_for)
    r = await tool.execute("{}")
    assert r.is_error is True
    assert "超时" in r.content


async def test_execute_bad_json_args() -> None:
    session = StubSession(result=_result_with_blocks([]))
    tool = _new_tool(session, name="er4")
    r = await tool.execute("{not json")
    assert r.is_error is True
    assert "参数解析失败" in r.content
    assert session.calls == []  # 未触发 call_tool


async def test_execute_non_text_blocks_dropped_warn_once(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_tool, "_non_text_warn_once", set())
    img = mtypes.ImageContent(type="image", data="aGk=", mimeType="image/png")
    session = StubSession(
        result=_result_with_blocks(
            [
                mtypes.TextContent(type="text", text="t1"),
                img,
                mtypes.TextContent(type="text", text="t2"),
            ]
        )
    )
    tool = _new_tool(session, name="mix")
    r1 = await tool.execute("{}")
    assert r1.content == "t1\nt2"
    err1 = capsys.readouterr().err
    assert "non-text content blocks" in err1

    # 同 full_name 第二次不再告警
    r2 = await tool.execute("{}")
    assert r2.content == "t1\nt2"
    err2 = capsys.readouterr().err
    assert "non-text content blocks" not in err2
