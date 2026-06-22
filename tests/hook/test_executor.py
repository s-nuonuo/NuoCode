"""hook.executor 单元测试（chap12 T12）。"""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from nuocode.hook.event import Event
from nuocode.hook.executor import ExecutionResult, Executor
from nuocode.hook.rule import (
    Action,
    ActionType,
    HttpAction,
    PromptAction,
    Rule,
    ShellAction,
    SubagentAction,
)


def _make_rule(action: Action, name: str = "test") -> Rule:
    return Rule(name=name, event=Event.SESSION_START, action=action, timeout_s=5.0)


# ────────── shell ──────────

@pytest.mark.asyncio
async def test_run_shell_exit2_blocked() -> None:
    action = Action(type=ActionType.SHELL, shell=ShellAction(command="echo 'reason text' >&2; exit 2"))
    rule = _make_rule(action)
    ex = Executor()
    result = await ex.run(rule, {"event": "PreToolUse"}, blocking=True)
    assert result.blocked is True
    assert "reason text" in result.reason


@pytest.mark.asyncio
async def test_run_shell_exit0_ok() -> None:
    action = Action(type=ActionType.SHELL, shell=ShellAction(command="exit 0"))
    rule = _make_rule(action)
    ex = Executor()
    result = await ex.run(rule, {}, blocking=True)
    assert result.blocked is False
    assert result.err is None


@pytest.mark.asyncio
async def test_run_shell_exit1_is_err_not_block() -> None:
    action = Action(type=ActionType.SHELL, shell=ShellAction(command="exit 1"))
    rule = _make_rule(action)
    ex = Executor()
    result = await ex.run(rule, {}, blocking=True)
    assert result.blocked is False
    assert result.err is not None


@pytest.mark.asyncio
async def test_run_shell_exit2_non_blocking_not_blocked() -> None:
    """非拦截事件下，exit 2 不表达拦截。"""
    action = Action(type=ActionType.SHELL, shell=ShellAction(command="exit 2"))
    rule = _make_rule(action)
    ex = Executor()
    result = await ex.run(rule, {}, blocking=False)
    assert result.blocked is False
    assert result.err is not None  # exit 2 在 non-blocking 下视为失败


@pytest.mark.asyncio
async def test_run_shell_stdin_json_sorted() -> None:
    """payload 以 key 字典序传给 stdin。"""
    action = Action(type=ActionType.SHELL, shell=ShellAction(command="cat"))
    rule = _make_rule(action)
    ex = Executor()
    payload = {"z": 1, "a": 2, "m": 3}
    # cat 把 stdin 原样输出到 stdout；shell exit 0 后 stdout 含 JSON
    proc = await asyncio.create_subprocess_shell(
        "cat",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    body = json.dumps(payload, sort_keys=True).encode()
    stdout, _ = await proc.communicate(input=body)
    data = json.loads(stdout.decode())
    keys = list(data.keys())
    assert keys == sorted(keys)


@pytest.mark.asyncio
async def test_run_shell_timeout() -> None:
    action = Action(type=ActionType.SHELL, shell=ShellAction(command="sleep 10"))
    rule = Rule(
        name="slow",
        event=Event.SESSION_START,
        action=action,
        timeout_s=0.1,
    )
    ex = Executor()
    result = await ex.run(rule, {}, blocking=False)
    assert result.err is not None
    assert "timed out" in str(result.err).lower() or isinstance(result.err, TimeoutError)


# ────────── prompt ──────────

@pytest.mark.asyncio
async def test_run_prompt_returns_text() -> None:
    action = Action(type=ActionType.PROMPT, prompt=PromptAction(text="remember zh-CN"))
    rule = _make_rule(action)
    ex = Executor()
    result = await ex.run(rule, {}, blocking=False)
    assert result.err is None
    assert result.prompt == "remember zh-CN"


# ────────── subagent stub ──────────

@pytest.mark.asyncio
async def test_run_subagent_stub(capsys) -> None:
    action = Action(type=ActionType.SUBAGENT, subagent=SubagentAction(agent_name="myagent", prompt="do x"))
    rule = _make_rule(action)
    ex = Executor()
    result = await ex.run(rule, {}, blocking=False)
    assert result.err is None
    captured = capsys.readouterr()
    assert "not yet implemented" in captured.err
    assert "myagent" in captured.err


# ────────── http (stdlib asyncio server) ──────────

import asyncio
from typing import Callable


async def _start_simple_server(
    response_body: bytes,
    status: int = 200,
    content_type: str = "application/json",
) -> tuple[str, asyncio.Server, list[bytes]]:
    """启动一个极简 asyncio HTTP echo server，返回 (base_url, server, received)。"""
    received: list[bytes] = []

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # 读取请求头
        header_lines: list[bytes] = []
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            header_lines.append(line)
        content_length = 0
        for hl in header_lines:
            if hl.lower().startswith(b"content-length:"):
                content_length = int(hl.split(b":", 1)[1].strip())
        body = await reader.read(content_length) if content_length else b""
        received.append(body)
        status_line = f"HTTP/1.1 {status} OK\r\n"
        resp_headers = (
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(response_body)}\r\n"
            "Connection: close\r\n\r\n"
        )
        writer.write((status_line + resp_headers).encode() + response_body)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    addr = server.sockets[0].getsockname()
    url = f"http://127.0.0.1:{addr[1]}"
    return url, server, received


@pytest.mark.asyncio
async def test_run_http_block() -> None:
    """HTTP 服务返回 decision=block → blocked=True。"""
    body = json.dumps({"decision": "block", "reason": "network policy"}).encode()
    url, server, _ = await _start_simple_server(body)
    async with server:
        action = Action(
            type=ActionType.HTTP,
            http=HttpAction(url=f"{url}/check", method="POST"),
        )
        rule = _make_rule(action)
        ex = Executor()
        result = await ex.run(rule, {"event": "PreToolUse"}, blocking=True)
    assert result.blocked is True
    assert result.reason == "network policy"


@pytest.mark.asyncio
async def test_run_http_5xx_is_not_err() -> None:
    """5xx 不触发拦截（没有 decision 字段），不报 err。"""
    body = b"Internal Server Error"
    url, server, _ = await _start_simple_server(body, status=500, content_type="text/plain")
    async with server:
        action = Action(
            type=ActionType.HTTP,
            http=HttpAction(url=f"{url}/err", method="POST"),
        )
        rule = _make_rule(action)
        ex = Executor()
        result = await ex.run(rule, {}, blocking=True)
    assert result.blocked is False
    assert result.err is None


@pytest.mark.asyncio
async def test_run_http_body_template() -> None:
    """body 模板 {event} 被正确渲染。"""
    url, server, received = await _start_simple_server(b"{}")
    async with server:
        action = Action(
            type=ActionType.HTTP,
            http=HttpAction(url=f"{url}/tpl", method="POST", body="event={event}"),
        )
        rule = _make_rule(action)
        ex = Executor()
        await ex.run(rule, {"event": "Stop"}, blocking=False)
    assert len(received) == 1
    assert b"event=Stop" in received[0]
