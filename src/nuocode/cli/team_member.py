"""--team-member 自治循环（chap15 T29）。

Pane 后端子进程：python -m nuocode --team-member 时执行本模块。
无 TUI，持续读 mailbox → 执行 Agent → 写结果回 mailbox/Lead。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any


async def run_team_member(
    agent_id: str,
    team_name: str,
    member_name: str,
    worktree_path: str,
    session_dir: str,
    model: str = "",
    plan_mode_required: bool = False,
) -> None:
    """Pane 后端队员自治主循环（F49-F51）。

    1. 初始化（config、registry、team_mgr、engine）
    2. 读 initial_prompt mailbox → 作为第一条 user 消息执行
    3. Loop：读邮件 → ingest → Agent.run → idle 通知 Lead → 等下一条
    """
    from nuocode.config import load, ConfigError
    from nuocode.agent import Agent
    from nuocode.agent.runtime import SessionRuntime
    from nuocode.agent.team_hook import IncomingMessage, TeammateContext, WITH_TEAMMATE_KEY
    from nuocode.agent.team_mailbox import ingest_team_mailbox
    from nuocode.compact import new_session_context
    from nuocode.conversation import Conversation
    from nuocode.permission import Mode, new_engine
    from nuocode.team.mailbox import Box
    from nuocode.team.mailbox.message import Message, MessageType
    from nuocode.tool import new_default_registry

    root = worktree_path if worktree_path else str(Path.cwd().resolve())

    # 加载配置
    try:
        cfg = load(str(Path(root) / ".nuocode/config.yaml"))
    except ConfigError:
        cfg = load(str(Path.home() / ".nuocode/config.yaml")) if (
            Path.home() / ".nuocode/config.yaml"
        ).exists() else None

    # 初始化
    registry = new_default_registry()
    engine, _ = new_engine(root)
    session_ctx = new_session_context(session_dir)
    runtime = SessionRuntime(session=session_ctx)

    # Team mailbox
    from nuocode.team.manager import Manager as TeamManager
    from nuocode.team.registry import AgentNameRegistry

    name_reg = AgentNameRegistry()
    from nuocode.task import Manager as TaskManager
    task_mgr = TaskManager()
    team_mgr = TeamManager(
        home_dir=Path.home(),
        project_root=Path(root),
        wt_mgr=None,
        task_mgr=task_mgr,
        registry=name_reg,
    )
    team = team_mgr.get(team_name)
    if team is None:
        print(f"[team-member] team {team_name!r} 不存在", file=sys.stderr)
        return

    box = Box(team.mailbox_dir)

    async def _read_unread() -> tuple[list[int], list[IncomingMessage]]:
        indices, messages = await box.read_unread(agent_id)
        return indices, [
            IncomingMessage(
                from_=m.from_,
                to=m.to,
                type=str(m.type),
                summary=m.summary,
                content=m.content,
                payload=m.payload,
                timestamp=m.timestamp,
            )
            for m in messages
        ]

    async def _mark_read(indices: list[int]) -> None:
        await box.mark_read(agent_id, indices)

    tc = TeammateContext(
        team_name=team_name,
        member_name=member_name,
        agent_id=agent_id,
        mailbox_dir=team.mailbox_dir,
        backend_type="tmux",
        read_unread=_read_unread,
        mark_read=_mark_read,
    )

    # 系统提示词
    from nuocode.team.spawn import team_system_prompt_suffix, build_team_context_reminder
    system_suffix = team_system_prompt_suffix()
    ctx_reminder = build_team_context_reminder(team, member_name, agent_id)

    # 权限模式
    perm_mode = Mode.PLAN if plan_mode_required else Mode.DEFAULT

    # providers
    providers = getattr(cfg, "providers", []) if cfg else []

    agent = Agent(
        provider=providers[0] if providers else None,
        registry=registry,
        version="0.1.0",
        engine=engine,
        runtime=runtime,
        context_window=None,
        system_prompt=system_suffix,
        max_turns=0,
        permission_mode=perm_mode,
        dont_ask=True,
        allowed_tools=None,
    )
    agent._extra_ctx = {WITH_TEAMMATE_KEY: tc}

    conv = Conversation()
    conv.add_system(ctx_reminder)

    print(f"[team-member] {member_name}({agent_id}) 准备就绪，等待任务...", file=sys.stderr)

    # 通知 Lead 成员已就绪
    _notify_lead_ready(box, team, agent_id, member_name)

    # 主循环
    while True:
        # 注入邮件
        await ingest_team_mailbox(tc, runtime, agent)

        # 检查是否有 pending 消息（通过 runtime）
        reminders = getattr(runtime, "pending_reminders", [])
        if reminders:
            # 有消息，唤醒并执行
            conv.add_user("\n".join(reminders))
            runtime.pending_reminders = []

            try:
                async for _chunk in agent.run(conv, ctx=agent._extra_ctx):
                    pass
            except Exception as e:  # noqa: BLE001
                print(f"[team-member] Agent 执行出错: {e}", file=sys.stderr)

            # 通知 Lead idle
            await _notify_lead_idle(box, team, agent_id, member_name)

        await asyncio.sleep(0.5)


def _notify_lead_ready(box: Any, team: Any, agent_id: str, member_name: str) -> None:
    """发送 ready 通知（fire-and-forget，非 async）。"""
    import asyncio
    asyncio.create_task(
        _async_notify_lead_ready(box, team, agent_id, member_name)
    )


async def _async_notify_lead_ready(box: Any, team: Any, agent_id: str, member_name: str) -> None:
    from nuocode.team.mailbox.message import Message, MessageType
    lead_id = team.lead_agent_id
    msg = Message(
        from_=agent_id,
        to=lead_id,
        type=MessageType.TEXT,
        summary=f"{member_name} 就绪",
        content=f"队员 {member_name}({agent_id}) 已就绪，等待任务",
    )
    try:
        await box.write(lead_id, msg)
    except Exception:  # noqa: BLE001
        pass


async def _notify_lead_idle(box: Any, team: Any, agent_id: str, member_name: str) -> None:
    """任务完成后通知 Lead idle（F50）。"""
    from nuocode.team.mailbox.message import Message, MessageType
    import time

    lead_id = team.lead_agent_id
    msg = Message(
        from_=agent_id,
        to=lead_id,
        type=MessageType.TEXT,
        summary=f"{member_name} 已空闲",
        content=f"队员 {member_name}({agent_id}) 已完成当前任务，空闲等待新指令",
        timestamp=int(time.time()),
    )
    try:
        await box.write(lead_id, msg)
    except Exception:  # noqa: BLE001
        pass


def main_team_member() -> None:
    """--team-member 入口（F48）。"""
    import argparse
    parser = argparse.ArgumentParser(prog="nuocode --team-member", add_help=True)
    parser.add_argument("--agent-id", required=True, help="预生成的 agent_id")
    parser.add_argument("--team", required=True, help="team name")
    parser.add_argument("--member", required=True, help="member name")
    parser.add_argument("--worktree", default="", help="worktree 目录")
    parser.add_argument("--session-dir", default="", help="session 目录")
    parser.add_argument("--model", default="", help="模型名")
    parser.add_argument("--plan-mode", action="store_true", help="以 plan 模式启动")

    args = parser.parse_args(sys.argv[2:])  # sys.argv[1] == "--team-member"

    asyncio.run(
        run_team_member(
            agent_id=args.agent_id,
            team_name=args.team,
            member_name=args.member,
            worktree_path=args.worktree,
            session_dir=args.session_dir,
            model=args.model,
            plan_mode_required=args.plan_mode,
        )
    )
