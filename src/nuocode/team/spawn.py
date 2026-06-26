"""spawn_teammate 主流程（chap15 T18）。

由 agent.AgentTool 通过 TeamHook 接口调用。
"""

from __future__ import annotations

import secrets
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nuocode.agent.team_hook import TeamSpawnRequest
    from nuocode.team.manager import Manager
    from nuocode.team.types import Team


def team_system_prompt_suffix() -> str:
    """队员系统提示词附录（F39）。"""
    return (
        "\n\nIMPORTANT: You are running as an agent in a team.\n"
        "Just writing a response in text is not visible to others\n"
        "on your team - you MUST use the SendMessage tool.\n"
        "The user interacts primarily with the team lead.\n"
        "Your work is coordinated through the task system\n"
        "and teammate messaging."
    )


def build_team_context_reminder(
    team: Team,
    member_name: str,
    agent_id: str,
) -> str:
    """构造 <team-context> reminder（F40）。"""
    member_list = ", ".join(
        f"{m.name}({'lead' if m.name == 'lead' else 'member'})"
        for m in team.members
    )
    return (
        f"<team-context>\n"
        f"team: {team.name}\n"
        f"你的成员名: {member_name}\n"
        f"你的 agent_id: {agent_id}\n"
        f"worktree 目录: 待分配\n"
        f"当前团队成员: {member_list}\n"
        f"</team-context>"
    )


def truncate_for_summary(prompt: str, max_words: int = 8) -> str:
    """将 prompt 截断为摘要（5-10 词）。"""
    words = prompt.split()
    if len(words) <= max_words:
        return prompt
    return " ".join(words[:max_words]) + "..."


async def spawn_teammate(
    manager: Manager,
    req: TeamSpawnRequest,
    ctx: Any = None,
) -> str:
    """spawn 队员主流程（T18/F25）。

    1. 取 Team
    2. 校验调用者权限
    3. 解析 SubAgentDefinition
    4. 创建 Worktree
    5. 申请 session_dir
    6. 预生成 agent_id
    7. 构造 allowed tools（teammate=True）
    8. 构造 sub_agent + sub_conv（in-process）或预写 mailbox（Pane）
    9. backend.spawn
    10. registry.register
    11. team.add_member
    """
    from nuocode.team.backend import SpawnRequest, new_backend
    from nuocode.team.mailbox import Box
    from nuocode.team.mailbox.message import Message, MessageType
    from nuocode.team.types import InProcessTeammateNoSpawnError, TeammateInfo

    # 1. 取 Team
    team = manager.get(req.team_name)
    if team is None:
        from nuocode.team.types import TeamNotFoundError
        raise TeamNotFoundError(f"Team 不存在: {req.team_name!r}")

    # 2. 校验调用者权限（F25）
    if ctx is not None:
        from nuocode.agent.team_hook import teammate_context_from_ctx
        tc = teammate_context_from_ctx(ctx)
        if tc is not None and tc.backend_type == "in-process":
            raise InProcessTeammateNoSpawnError(
                "in-process 队员不允许再 spawn Team 队员（F25）"
            )

    # 3. 解析 SubAgentDefinition
    definition = _resolve_definition(manager, req, team)

    # 4. 创建 Worktree
    sanitized_team = team.sanitized_name
    member_name = req.member_name or f"member-{secrets.token_hex(3)}"
    wt_slug = f"team-{sanitized_team}/{member_name}"
    worktree_path = ""

    if manager.wt_mgr is not None:
        try:
            session = await manager.wt_mgr.create(wt_slug, "HEAD", False)
            worktree_path = str(session.worktree_path)
            branch = getattr(session, "branch", "")
        except Exception as e:
            print(f"[team] 创建 worktree 失败（继续）: {e}", file=sys.stderr)
            branch = ""
    else:
        branch = ""

    # 5. 申请 session_dir
    session_dir = _new_session_dir(manager.project_root)

    # 6. 预生成 agent_id
    agent_id = f"agent-{secrets.token_hex(7)}"

    # 7. 计算 allowed tools（teammate=True）
    full_tools = _get_full_tools(manager)
    from nuocode.tool.filter import FilterParams, apply_agent_tool_filter
    allowed_tools = apply_agent_tool_filter(
        FilterParams(
            all=full_tools,
            source=int(getattr(definition, "source", 0)),
            background=True,  # 队员始终后台
            allowed=list(getattr(definition, "tools", [])),
            disallowed=list(getattr(definition, "disallowed_tools", [])),
            teammate=True,
        )
    )

    system_prompt = (getattr(definition, "system_prompt", "") or "") + team_system_prompt_suffix()

    spawn_req = SpawnRequest(
        team_name=team.sanitized_name,
        member_name=member_name,
        agent_id=agent_id,
        worktree_path=worktree_path,
        session_dir=session_dir,
        agent_type=req.subagent_type or "",
        model=req.model or "",
        initial_prompt=req.prompt,
        plan_mode_required=req.plan_mode_required,
    )

    # 8. 按后端类型处理
    backend_type = team.backend
    pane_id = ""
    actual_agent_id = agent_id

    if str(backend_type) == "in-process":
        # 构造 sub_agent
        sub_agent, sub_conv = _build_in_process_agent(
            manager=manager,
            definition=definition,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            agent_id=agent_id,
            member_name=member_name,
            team=team,
            worktree_path=worktree_path,
            session_dir=session_dir,
        )
        spawn_req.sub_agent = sub_agent
        spawn_req.conv = sub_conv
        spawn_req.task_mgr = manager.task_mgr
        spawn_req.initial_prompt = req.prompt  # in-process 直接传 prompt

        backend = new_backend(backend_type, task_mgr=manager.task_mgr)
        pane_id, actual_agent_id = await backend.spawn(spawn_req)
        # in-process 后端返回的是 task_id 作为 agent_id
        if actual_agent_id:
            agent_id = actual_agent_id

    else:
        # Pane 后端：预写 initial_prompt 到 mailbox
        box = Box(team.mailbox_dir)
        init_msg = Message(
            from_="lead",
            to=agent_id,
            type=MessageType.TEXT,
            summary=truncate_for_summary(req.prompt),
            content=req.prompt,
        )
        await box.write(agent_id, init_msg)

        backend = new_backend(backend_type, task_mgr=manager.task_mgr)
        pane_id, actual_agent_id = await backend.spawn(spawn_req)

    # 9. 注册
    if manager.registry is not None:
        manager.registry.register(member_name, agent_id)

    # 10. 加入 Team
    teammate = TeammateInfo(
        name=member_name,
        agent_id=agent_id,
        agent_type=req.subagent_type or "",
        model=req.model or "",
        worktree_path=worktree_path,
        branch=branch,
        backend_type=backend_type,
        pane_id=pane_id,
        is_active=True,
        plan_mode_required=req.plan_mode_required,
        session_dir=session_dir,
    )
    await team.add_member(teammate)

    import json
    return json.dumps(
        {
            "member_name": member_name,
            "agent_id": agent_id,
            "worktree": worktree_path,
            "backend": str(backend_type),
            "pane_id": pane_id,
        },
        ensure_ascii=False,
    )


def _resolve_definition(manager: Manager, req: TeamSpawnRequest, team: Team) -> Any:
    """解析 SubAgentDefinition（F25 步骤 3）。"""
    # 尝试从 Manager 的 agent 上下文取 catalog
    catalog = getattr(manager, "_catalog", None)
    if catalog is None:
        # 创建 fallback 空 definition
        return _FallbackDefinition(name=req.subagent_type or "general-purpose")

    if req.subagent_type:
        definition = catalog.resolve(req.subagent_type)
        if definition is None:
            return _FallbackDefinition(name=req.subagent_type)
        return definition

    return _FallbackDefinition(name="general-purpose")


class _FallbackDefinition:
    """当 Catalog 不可用时的后备 Definition。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.system_prompt = ""
        self.max_turns = 0
        self.permission_mode = None
        self.dont_ask = True
        self.tools: list[str] = []
        self.disallowed_tools: list[str] = []
        self.source = 0
        self.isolation = ""


def _get_full_tools(manager: Manager) -> list[str]:
    """获取全量工具名列表。"""
    # 尝试从 manager 持有的 registry（tool registry，非 AgentNameRegistry）取
    tool_registry = getattr(manager, "_tool_registry", None)
    if tool_registry is not None:
        return tool_registry.names()

    # 构造基础工具集
    return [
        "read_file", "write_file", "edit_file", "glob", "grep", "bash",
        "load_skill", "install_skill",
        "TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "SendMessage",
    ]


def _new_session_dir(project_root: Path) -> str:
    """申请新的 session 目录（沿用 ch12 格式）。"""
    import uuid
    session_id = uuid.uuid4().hex[:12]
    session_dir = project_root / ".nuocode" / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return str(session_dir)


def _build_in_process_agent(
    manager: Manager,
    definition: Any,
    system_prompt: str,
    allowed_tools: list[str],
    agent_id: str,
    member_name: str,
    team: Team,
    worktree_path: str,
    session_dir: str,
) -> tuple[Any, Any]:
    """构造 in-process 子 Agent 和对话（F25 步骤 8）。"""
    from nuocode.agent.team_hook import (
        IncomingMessage,
        TeammateContext,
    )
    from nuocode.team.mailbox import Box

    parent_agent = getattr(manager, "_parent_agent", None)
    if parent_agent is None:
        raise RuntimeError("Manager 未绑定 parent_agent，无法构造 in-process 子 Agent")

    from nuocode.agent import Agent
    from nuocode.agent.runtime import SessionRuntime
    from nuocode.compact import new_session_context
    from nuocode.conversation import Conversation
    from nuocode.permission import Mode, new_engine

    # 权限引擎（worktree_path 或 project_root）
    sub_root = worktree_path if worktree_path else str(manager.project_root)
    sub_engine, _ = new_engine(sub_root)

    # runtime
    sub_session_dir = session_dir if session_dir else tempfile.gettempdir()
    sub_runtime = SessionRuntime(session=new_session_context(sub_session_dir))

    # 权限模式
    if getattr(definition, "plan_mode_required", False):
        from nuocode.permission import Mode
        sub_mode = Mode.PLAN
    else:
        sub_mode = getattr(definition, "permission_mode", None)

    sub_agent = Agent(
        provider=parent_agent._provider,
        registry=parent_agent._registry,
        version=parent_agent._version,
        engine=sub_engine,
        runtime=sub_runtime,
        context_window=parent_agent._context_window,
        system_prompt=system_prompt or None,
        max_turns=getattr(definition, "max_turns", 0),
        permission_mode=sub_mode,
        dont_ask=True,  # F39a：队员始终 dont_ask=True
        allowed_tools=allowed_tools if allowed_tools else None,
    )

    # 注入 <team-context> reminder
    team_context_reminder = build_team_context_reminder(team, member_name, agent_id)

    sub_conv = Conversation()
    sub_conv.add_system(team_context_reminder)

    # 构造 TeammateContext，用闭包包装 mailbox 操作
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
        team_name=team.sanitized_name,
        member_name=member_name,
        agent_id=agent_id,
        mailbox_dir=team.mailbox_dir,
        backend_type="in-process",
        read_unread=_read_unread,
        mark_read=_mark_read,
    )

    # 把 TeammateContext 注入到 sub_agent 的 extra_ctx
    # agent.Agent 通过 _extra_ctx 传递给 execute 的 ctx 参数
    sub_agent._extra_ctx = {**getattr(sub_agent, "_extra_ctx", {})}
    from nuocode.agent.team_hook import WITH_TEAMMATE_KEY
    sub_agent._extra_ctx[WITH_TEAMMATE_KEY] = tc

    return sub_agent, sub_conv
