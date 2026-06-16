"""端到端冒烟脚本：发送一条消息，打印每轮缓存用量。

用法（以 anthropic 为例，依赖 .nuocode/config.yaml 已配置 provider）::

    python examples/smoke.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from nuocode import permission
from nuocode.agent import Agent
from nuocode.config import load
from nuocode.conversation import Conversation
from nuocode.llm import new_provider
from nuocode.permission import Mode
from nuocode.tool import new_default_registry


async def _main() -> int:
    try:
        cfg = load(".nuocode/config.yaml")
    except Exception as e:  # noqa: BLE001
        print(f"未找到合法配置：{e}", file=sys.stderr)
        return 2
    if not cfg.providers:
        print("未配置任何 provider，请先编辑 .nuocode/config.yaml", file=sys.stderr)
        return 2
    p = new_provider(cfg.providers[0])
    cwd = str(Path.cwd().resolve())
    engine, _ = permission.new_engine(cwd)
    agent = Agent(p, new_default_registry(), "dev", engine)

    conv = Conversation()
    for turn, prompt_text in enumerate(["你好，请简单介绍一下你自己。", "我现在的工作目录是？"], 1):
        conv.add_user(prompt_text)
        print(f"\n=== Turn {turn} ===")
        # BYPASS：非交互冒烟无人在回路；黑名单/沙箱仍生效。
        async for ev in agent.run(conv, Mode.BYPASS):
            if ev.text:
                print(ev.text, end="", flush=True)
            if ev.usage is not None:
                u = ev.usage
                print(
                    f"\n[usage] input={u.input} output={u.output} "
                    f"cache_write={u.cache_write} cache_read={u.cache_read}"
                )
            if ev.tool is not None and ev.tool.phase.name == "END":
                print(f"[tool {ev.tool.name}] -> {ev.tool.result[:80]}")
            if ev.done:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
