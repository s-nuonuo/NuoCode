"""MCP 连接管理器：并发连接所有 server、缓存会话、统一关闭。

- 连接 / 握手 / 列工具 受 :data:`connect_timeout`（默认 30s）约束。
- 关闭 受 :data:`close_timeout`（默认 5s）兜底，绝不阻塞退出。
- 单 server 失败 / 超时 仅 stderr 告警跳过，绝不抛出。
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

import mcp.types as mtypes
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from nuocode.mcp.config import Config, ServerConfig
from nuocode.mcp.tool import McpTool, adapt_tool

connect_timeout: float = 30.0
close_timeout: float = 5.0


@dataclass
class _Session:
    name: str
    session: ClientSession


@dataclass
class Manager:
    """成功建立的会话与适配好的工具集合，统一生命周期。"""

    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _sessions: list[_Session] = field(default_factory=list)
    _tools: list[McpTool] = field(default_factory=list)
    _stack: AsyncExitStack = field(default_factory=AsyncExitStack)
    _entered: bool = False

    def tools(self) -> list[McpTool]:
        """返回适配好的工具列表副本（按 ``full_name`` 排序）。"""
        return list(self._tools)

    async def close(self) -> None:
        """统一关闭所有上下文；5s 兜底超时；告警后不再等。"""
        if not self._entered:
            return
        self._entered = False
        try:
            await asyncio.wait_for(self._stack.aclose(), timeout=close_timeout)
        except TimeoutError:
            print(
                f"[mcp] warn: close timeout ({close_timeout}s), some sessions may leak",
                file=sys.stderr,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[mcp] warn: close error: {e}", file=sys.stderr)


async def _do_connect(mgr: Manager, name: str, srv: ServerConfig, version: str) -> None:
    """建立单个 server 的 transport + ClientSession，握手并列工具。"""
    if srv.type == "stdio":
        params = StdioServerParameters(
            command=srv.command,
            args=list(srv.args),
            env={**os.environ, **srv.env},
        )
        ctx: Any = stdio_client(params)
    else:
        ctx = streamablehttp_client(srv.url, headers=srv.headers or None)

    transport = await mgr._stack.enter_async_context(ctx)
    # stdio 返回 (read, write)；http 返回 (read, write, _metadata)。
    read, write = transport[0], transport[1]

    session = await mgr._stack.enter_async_context(
        ClientSession(
            read,
            write,
            client_info=mtypes.Implementation(name="nuocode", version=version),
        )
    )
    await session.initialize()
    listed = await session.list_tools()

    adapted: list[McpTool] = []
    for t in listed.tools:
        a = adapt_tool(name, t, session)
        if a is not None:
            adapted.append(a)

    async with mgr._lock:
        mgr._sessions.append(_Session(name=name, session=session))
        mgr._tools.extend(adapted)


async def _connect_one(mgr: Manager, name: str, srv: ServerConfig, version: str) -> None:
    """单 server 连接的外层守护：超时 / 异常 仅告警跳过。"""
    try:
        await asyncio.wait_for(_do_connect(mgr, name, srv, version), timeout=connect_timeout)
    except TimeoutError:
        print(
            f"[mcp] warn: connect server {name} timeout after {connect_timeout}s",
            file=sys.stderr,
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[mcp] warn: connect server {name} failed: {e}", file=sys.stderr)


async def new_manager(cfg: Config, version: str) -> Manager:
    """并发连接所有 server，全部尝试结束后返回。

    使用 :func:`asyncio.gather` ``return_exceptions=True`` 双保险：``_connect_one``
    内部已捕获，理论上不会有异常上抛。
    """
    mgr = Manager()
    await mgr._stack.__aenter__()
    mgr._entered = True

    tasks = [
        asyncio.create_task(_connect_one(mgr, name, srv, version))
        for name, srv in cfg.servers.items()
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    mgr._tools.sort(key=lambda t: t.full_name)
    return mgr


__all__ = [
    "Manager",
    "close_timeout",
    "connect_timeout",
    "new_manager",
]
