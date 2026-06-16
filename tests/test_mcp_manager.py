"""tests for nuocode.mcp.manager: 连接成功/失败/超时、close 不死锁、稳定排序。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from nuocode.mcp import manager as mcp_mgr
from nuocode.mcp.config import Config, ServerConfig
from nuocode.mcp.tool import McpTool


def _empty_cfg() -> Config:
    return Config(servers={})


async def test_new_manager_empty_cfg() -> None:
    mgr = await mcp_mgr.new_manager(_empty_cfg(), version="0.0")
    assert mgr.tools() == []
    await mgr.close()


def _make_dummy_tool(full_name: str) -> McpTool:
    class _C:
        async def call_tool(self, name: str, arguments: dict[str, Any] | None) -> Any:
            raise NotImplementedError

    return McpTool(
        full_name=full_name,
        remote_name=full_name.split("__")[-1],
        description_text="d",
        parameters_schema={"type": "object"},
        read_only=False,
        caller=_C(),
    )


async def test_failure_isolated(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """一个 server 失败、一个成功——成功侧仍注册，失败仅告警。"""

    async def fake_do_connect(mgr: Any, name: str, srv: Any, version: str) -> None:
        if name == "bad":
            raise RuntimeError("boom")
        # good：直接附上一个工具到 mgr
        async with mgr._lock:
            mgr._tools.append(_make_dummy_tool(f"mcp__{name}__t1"))

    monkeypatch.setattr(mcp_mgr, "_do_connect", fake_do_connect)

    cfg = Config(
        servers={
            "bad": ServerConfig(type="stdio", command="x"),
            "good": ServerConfig(type="stdio", command="x"),
        }
    )
    mgr = await mcp_mgr.new_manager(cfg, version="0.0")
    names = [t.name() for t in mgr.tools()]
    assert names == ["mcp__good__t1"]
    err = capsys.readouterr().err
    assert "bad" in err and "failed" in err
    await mgr.close()


async def test_connect_timeout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """卡住的 server 应在超时窗口内被跳过。"""

    async def stuck(mgr: Any, name: str, srv: Any, version: str) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(mcp_mgr, "_do_connect", stuck)
    monkeypatch.setattr(mcp_mgr, "connect_timeout", 0.15)

    cfg = Config(servers={"slow": ServerConfig(type="stdio", command="x")})
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    mgr = await mcp_mgr.new_manager(cfg, version="0.0")
    elapsed = loop.time() - t0
    assert elapsed < 1.0
    assert mgr.tools() == []
    assert "timeout" in capsys.readouterr().err.lower()
    await mgr.close()


async def test_close_timeout_does_not_block(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """注入 close 卡住的上下文，验证 close 在 close_timeout 内返回。"""

    class BlockingCtx:
        async def __aenter__(self) -> str:
            return "x"

        async def __aexit__(self, *a: Any) -> None:
            await asyncio.Event().wait()

    async def fake_do_connect(mgr: Any, name: str, srv: Any, version: str) -> None:
        await mgr._stack.enter_async_context(BlockingCtx())

    monkeypatch.setattr(mcp_mgr, "_do_connect", fake_do_connect)
    monkeypatch.setattr(mcp_mgr, "close_timeout", 0.15)

    cfg = Config(servers={"s": ServerConfig(type="stdio", command="x")})
    mgr = await mcp_mgr.new_manager(cfg, version="0.0")

    loop = asyncio.get_event_loop()
    t0 = loop.time()
    await mgr.close()
    elapsed = loop.time() - t0
    assert elapsed < 1.0
    assert "close timeout" in capsys.readouterr().err


async def test_tools_sorted_by_full_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """注册顺序与 task 完成顺序无关，最终按 full_name 稳定排序。"""

    async def fake_do_connect(mgr: Any, name: str, srv: Any, version: str) -> None:
        # 让 z 比 a 先完成
        if name == "a":
            await asyncio.sleep(0.05)
        async with mgr._lock:
            mgr._tools.append(_make_dummy_tool(f"mcp__{name}__t"))

    monkeypatch.setattr(mcp_mgr, "_do_connect", fake_do_connect)
    cfg = Config(
        servers={
            "z": ServerConfig(type="stdio", command="x"),
            "a": ServerConfig(type="stdio", command="x"),
        }
    )
    mgr = await mcp_mgr.new_manager(cfg, version="0.0")
    names = [t.name() for t in mgr.tools()]
    assert names == ["mcp__a__t", "mcp__z__t"]
    await mgr.close()
