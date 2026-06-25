"""Skill Executor：inline / fork 两种执行模式。"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from nuocode.skills.active import ActiveSkills
from nuocode.skills.catalog import Catalog
from nuocode.skills.render import render_body


@dataclass
class ExecuteRequest:
    skill_name: str
    args: str = ""


@dataclass
class ExecuteEvent:
    kind: Literal["inline_inject", "fork_started", "fork_done", "error", "info"]
    text: str = ""
    body: str = ""


class Executor:
    """根据 Skill.meta.mode 分发 inline / fork。

    - inline：把 SOP 注入 active_skills，并把 rendered body 作为新一条 user message 入 Conversation；
      由 caller 直接驱动 Agent.run（这里只产 inline_inject 事件 + 文本）。
    - fork：spawn 子 Agent 同进程任务；按 fork_context 复制消息子集；
      使用 full_registry.definitions_filtered(allowed) 限定工具集。
    """

    def __init__(self, catalog: Catalog, active: ActiveSkills, work_dir: Path) -> None:
        self._catalog = catalog
        self._active = active
        self._work_dir = Path(work_dir)

    async def execute(
        self,
        req: ExecuteRequest,
        *,
        agent=None,  # noqa: ANN001  # 用于 fork 模式 spawn 子 Agent
        conv=None,  # noqa: ANN001
        registry=None,  # noqa: ANN001
        provider=None,  # noqa: ANN001
        engine=None,  # noqa: ANN001
        version: str = "0.0.0",
    ) -> AsyncIterator[ExecuteEvent]:
        sk = self._catalog.get(req.skill_name)
        if sk is None:
            yield ExecuteEvent(kind="error", text=f"unknown skill: {req.skill_name}")
            return

        body = render_body(sk, req.args)

        if not sk.meta.is_fork():
            # inline：激活 + 把 body 当作下一条 user 消息
            self._active.activate(sk.meta.name, body)
            yield ExecuteEvent(kind="inline_inject", body=body)
            return

        # fork：必须由 caller 传入 conv/registry/provider/engine 才能真正 spawn
        if registry is None or provider is None or engine is None or conv is None:
            yield ExecuteEvent(
                kind="error",
                text="fork mode requires registry/provider/engine/conv from caller",
            )
            return

        # 构造 fork 子 Agent 的 messages：根据 fork_context 截取
        from nuocode.agent.launch import launch_fork
        from nuocode.conversation import Conversation

        fc = sk.meta.fork_context
        msgs = conv.messages()
        if fc == "none":
            sub_msgs = []
        elif fc == "recent":
            sub_msgs = msgs[-10:] if len(msgs) > 10 else list(msgs)
        else:  # "full" → 简化：与 recent 同；提示
            print(
                f"[skills] info: skill {sk.meta.name} fork_context=full simplified to 'recent'",
                file=sys.stderr,
            )
            sub_msgs = list(msgs)

        # 用 launch_fork 公共路径（chap13 F33）
        # 构造临时父 Agent 代理，仅用于传递 provider/registry/engine/version

        class _ParentProxy:
            """临时父 Agent 代理。"""
            def __init__(self) -> None:
                self._provider = provider
                self._registry = registry
                self._version = version
                self._engine = engine
                self._context_window = 200_000

        proxy = _ParentProxy()

        # 构造截断后的 conv
        parent_conv_fork = Conversation()
        parent_conv_fork.replace_messages(sub_msgs)

        yield ExecuteEvent(kind="fork_started", text=sk.meta.name)
        try:
            final_text = await launch_fork(
                parent_agent=proxy,
                parent_conv=parent_conv_fork,
                task=body,
                allowed_tools=sk.meta.allowed_tools or None,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            yield ExecuteEvent(kind="error", text=f"fork skill error: {e}")
            return
        yield ExecuteEvent(
            kind="fork_done", text=sk.meta.name, body=final_text
        )


__all__ = ["ExecuteEvent", "ExecuteRequest", "Executor"]
