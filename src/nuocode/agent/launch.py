"""launch_fork：SubAgent 公共启动函数（chap13 F33）。

供 Skill fork 路径复用——避免两套构造逻辑并存。
"""

from __future__ import annotations

import tempfile
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nuocode.subagent.definition import Definition


async def launch_fork(
    *,
    parent_agent: Any,         # nuocode.agent.Agent
    parent_conv: Any,          # nuocode.conversation.Conversation
    task: str,
    definition: Definition | None = None,
    system_prompt: str | None = None,
    allowed_tools: list[str] | None = None,
) -> str:
    """启动 Fork 子 Agent 并跑到底，返回 final_text（chap13 F33）。

    Args:
        parent_agent:   父 Agent（提供 provider/registry/engine/version）
        parent_conv:    父对话（用于克隆历史）
        task:           任务文本
        definition:     可选的 subagent.Definition（提供工具过滤/maxTurns 等）
        system_prompt:  覆盖默认 system prompt
        allowed_tools:  直接指定允许工具列表（优先于 definition 计算）

    Returns:
        子 Agent 的 final_text
    """
    from nuocode.agent import Agent, MaxTurnsReached
    from nuocode.agent.fork import build_forked_messages
    from nuocode.agent.runtime import SessionRuntime
    from nuocode.compact import new_session_context
    from nuocode.conversation import Conversation
    from nuocode.permission import new_engine

    # ── 独立运行时 ──
    sub_runtime = SessionRuntime(session=new_session_context(tempfile.gettempdir()))

    # ── 权限引擎（共享 root）──
    try:
        project_root = str(parent_agent._engine.root)
    except AttributeError:
        project_root = tempfile.gettempdir()
    sub_engine, _ = new_engine(project_root)

    # ── 工具白名单 ──
    if allowed_tools is None and definition is not None:
        from nuocode.tool.filter import FilterParams, apply_agent_tool_filter

        full_tools = parent_agent._registry.names()
        fp = FilterParams(
            all=full_tools,
            source=int(definition.source),
            background=False,  # Skill fork 不是后台
            allowed=list(definition.tools),
            disallowed=list(definition.disallowed_tools),
        )
        allowed_tools = apply_agent_tool_filter(fp)

    # ── permission_mode ──
    from nuocode.permission import Mode

    sub_mode: Mode | None = None
    if definition is not None:
        sub_mode = definition.permission_mode

    max_turns = 0
    if definition is not None and definition.max_turns > 0:
        max_turns = definition.max_turns

    # ── 构造子 Agent ──
    sub_agent = Agent(
        provider=parent_agent._provider,
        registry=parent_agent._registry,
        version=parent_agent._version,
        engine=sub_engine,
        runtime=sub_runtime,
        context_window=parent_agent._context_window,
        system_prompt=system_prompt,
        max_turns=max_turns,
        permission_mode=sub_mode,
        dont_ask=definition.dont_ask if definition is not None else False,
        allowed_tools=allowed_tools,
    )

    # ── 构造子对话（Fork 路径）──
    parent_msgs = list(parent_conv.messages())
    forked = build_forked_messages(parent_msgs, "")
    sub_conv = Conversation.from_messages(forked)

    # ── 跑到底 ──
    try:
        return await sub_agent.run_to_completion(sub_conv, task)
    except MaxTurnsReached as e:
        return e.final_text
