"""nuocode CLI 入口：加载配置 → 装配 MCP → 构造权限引擎 → 启动 TUI。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from nuocode.config import ConfigError, load


async def _amain() -> int:
    try:
        cfg = load(".nuocode/config.yaml")
    except ConfigError as e:
        print(f"[nuocode] 配置错误: {e}", file=sys.stderr)
        return 1

    from nuocode import mcp as mcp_client
    from nuocode import permission
    from nuocode.tool import new_default_registry
    from nuocode.tui.app import NuoCodeApp

    root = str(Path.cwd().resolve())
    engine, perm_err = permission.new_engine(root)
    if perm_err is not None:
        print(f"[nuocode] 权限引擎降级: {perm_err}", file=sys.stderr)

    registry = new_default_registry()

    mcp_cfg = mcp_client.load_config(root)
    try:
        version = __import__("nuocode").__version__
    except AttributeError:
        version = "0.1.0"
    mgr = await mcp_client.new_manager(mcp_cfg, version=version)

    try:
        for t in mgr.tools():
            try:
                registry.register(t)
            except ValueError as e:
                print(f"[mcp] warn: {e}", file=sys.stderr)

        app = NuoCodeApp(cfg.providers, registry, engine)
        try:
            await app.run_async()
        except KeyboardInterrupt:
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"[nuocode] 运行异常: {e}", file=sys.stderr)
            return 1
    finally:
        await mgr.close()
    return 0


def main() -> None:
    try:
        rc = asyncio.run(_amain())
    except KeyboardInterrupt:
        rc = 0
    if rc:
        sys.exit(rc)
