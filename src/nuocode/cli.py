"""nuocode CLI 入口：加载配置 → 装配 MCP → 构造权限引擎 → 启动 TUI。"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import sys
from pathlib import Path

from nuocode.config import ConfigError, load

logger = logging.getLogger(__name__)


async def _amain() -> int:
    try:
        cfg = load(".nuocode/config.yaml")
    except ConfigError as e:
        print(f"[nuocode] 配置错误: {e}", file=sys.stderr)
        return 1

    from nuocode import instructions as instructions_mod
    from nuocode import mcp as mcp_client
    from nuocode import memory as memory_mod
    from nuocode import permission
    from nuocode import session as session_mod
    from nuocode.agent.runtime import SessionRuntime
    from nuocode.compact import new_session_context
    from nuocode.tool import new_default_registry
    from nuocode.tui.app import NuoCodeApp

    root = str(Path.cwd().resolve())

    # 项目指令加载（chap09）
    try:
        instruction_text = instructions_mod.Loader(root).load()
    except Exception as e:  # noqa: BLE001
        logger.warning("加载项目指令失败: %s", e)
        instruction_text = ""

    # 记忆管理器（chap09）
    project_mem_dir = str(Path(root) / ".nuocode" / "memory")
    user_mem_dir = str(Path.home() / ".nuocode" / "memory")
    mem_mgr = memory_mod.Manager(project_mem_dir, user_mem_dir, provider=None, model="")
    try:
        memory_text = mem_mgr.load_index()
    except Exception as e:  # noqa: BLE001
        logger.warning("加载记忆索引失败: %s", e)
        memory_text = ""

    engine, perm_err = permission.new_engine(root)
    if perm_err is not None:
        print(f"[nuocode] 权限引擎降级: {perm_err}", file=sys.stderr)
    registry = new_default_registry()

    # ── 会话上下文 + 运行时容器 ──
    session_ctx = new_session_context(root)
    runtime = SessionRuntime(session=session_ctx)
    sessions_dir = str(Path(root) / ".nuocode" / "sessions")

    # 会话 JSONL 写入器（chap09）
    writer = session_mod.Writer(session_ctx.session_dir)

    # 后台清理过期会话（chap09）
    asyncio.create_task(session_mod.clean_expired(sessions_dir, _dt.timedelta(days=30)))

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
        app = NuoCodeApp(
            cfg.providers,
            registry,
            engine,
            runtime,
            writer=writer,
            mem_mgr=mem_mgr,
            instruction_text=instruction_text,
            memory_text=memory_text,
            sessions_dir=sessions_dir,
        )
        try:
            await app.run_async()
        except KeyboardInterrupt:
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"[nuocode] 运行异常: {e}", file=sys.stderr)
            return 1
    finally:
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass
        await mgr.close()
    return 0


def main() -> None:
    try:
        rc = asyncio.run(_amain())
    except KeyboardInterrupt:
        rc = 0
    if rc:
        sys.exit(rc)
