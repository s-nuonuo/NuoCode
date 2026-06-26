"""队员 Loop 头部 incoming-messages 注入（chap15 T20）。

在 agent.Agent.run 每轮迭代前（调 LLM 前）读取 TeammateContext 的邮箱。
未读消息以 <incoming-messages> system reminder 形式注入 LLM 输入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nuocode.agent.team_hook import IncomingMessage, TeammateContext


async def ingest_team_mailbox(
    tc: TeammateContext,
    runtime: Any,
    agent: Any,
) -> None:
    """读取 TeammateContext 的未读邮箱，注入 reminder（T20/F41）。

    Args:
        tc: 当前队员的 TeammateContext
        runtime: SessionRuntime（含 pending_reminders）
        agent: Agent 实例（用于权限模式切换）
    """
    try:
        indices, unread = await tc.read_unread()
    except Exception:  # noqa: BLE001
        return

    if not unread:
        return

    # 构造 <incoming-messages> reminder（F42）
    reminder = _build_incoming_reminder(unread)
    if hasattr(runtime, "append_reminder"):
        runtime.append_reminder(reminder)
    elif hasattr(runtime, "pending_reminders"):
        runtime.pending_reminders.append(reminder)

    # 处理特殊消息类型
    for msg in unread:
        _handle_special_message(msg, agent)

    # 标记已读
    try:
        await tc.mark_read(indices)
    except Exception:  # noqa: BLE001
        pass


def _build_incoming_reminder(messages: list[IncomingMessage]) -> str:
    """构造 <incoming-messages> reminder 字符串（F42）。"""
    lines = [f"<incoming-messages>\n收到 {len(messages)} 条新消息:"]
    for i, msg in enumerate(messages, start=1):
        ts_str = str(msg.timestamp) if msg.timestamp else "unknown"
        content_preview = (msg.content or "")[:200]
        lines.append(
            f"[{i}] 来自 {msg.from_}(type={msg.type},ts={ts_str}): {msg.summary}\n"
            f"    {content_preview}"
        )
    lines.append("</incoming-messages>")
    return "\n".join(lines)


def _handle_special_message(msg: IncomingMessage, agent: Any) -> None:
    """处理特殊消息类型（F43-F44）。

    - plan_approval_response(approve=True)：切到 default 权限模式
    - plan_approval_response(approve=False)：在 reminder 中已体现
    """
    if msg.type == "plan_approval_response":
        payload = msg.payload or {}
        approve = payload.get("approve", False)
        if approve and agent is not None:
            try:
                from nuocode.permission import Mode
                if hasattr(agent, "set_permission_mode"):
                    agent.set_permission_mode(Mode.DEFAULT)
                elif hasattr(agent, "_permission_mode"):
                    agent._permission_mode = Mode.DEFAULT
            except Exception:  # noqa: BLE001
                pass
