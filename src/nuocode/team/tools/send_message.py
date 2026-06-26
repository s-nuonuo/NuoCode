"""SendMessage 工具（chap15 F31-F34）。"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from nuocode.tool import Result

if TYPE_CHECKING:
    from nuocode.team.manager import Manager


class SendMessageTool:
    """向 Team 成员发消息（F31-F34）。"""

    read_only = False

    def __init__(self, manager: Manager) -> None:
        self._manager = manager

    def name(self) -> str:
        return "SendMessage"

    def description(self) -> str:
        return (
            "向 Team 成员发送消息（仅 Team 队员可用，主 Agent 也可发送给队员）。\n"
            "- to: 队员名 / agent_id / \"*\" 广播\n"
            "- type: text / shutdown_request / shutdown_response / plan_approval_response\n"
            "已停止的 in-process 队员会自动续派。\n"
            "Pane 后端队员通过 send-keys 唤醒。"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "目标：队员名 / agent_id / \"*\" 广播（必填）",
                },
                "summary": {
                    "type": "string",
                    "description": "消息摘要 5-10 词（纯文本消息时必填）",
                },
                "message": {
                    "type": "string",
                    "description": "消息正文（可选）",
                },
                "type": {
                    "type": "string",
                    "enum": ["text", "shutdown_request", "shutdown_response", "plan_approval_response"],
                    "description": "消息类型（可选，默认 text）",
                },
                "payload": {
                    "type": "object",
                    "description": "结构化消息载荷（可选，如 plan_approval_response 的 {approve, feedback}）",
                },
            },
            "required": ["to"],
        }

    async def execute(self, args: str, ctx: Any = None) -> Result:
        try:
            params = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError):
            return Result(content="[SendMessage] 参数解析失败", is_error=True)

        to = params.get("to") or ""
        summary = params.get("summary") or ""
        message = params.get("message") or ""
        msg_type = params.get("type") or "text"
        payload = params.get("payload")

        if not to:
            return Result(content="[SendMessage] to 不能为空", is_error=True)

        # 获取当前 Team
        team = self._get_team(ctx)
        if team is None:
            return Result(content="[SendMessage] 无法获取当前 Team 上下文", is_error=True)

        # 确定发件人
        sender_agent_id = "lead"
        if ctx is not None:
            from nuocode.agent.team_hook import teammate_context_from_ctx
            tc = teammate_context_from_ctx(ctx)
            if tc is not None:
                sender_agent_id = tc.agent_id

        # 校验权限（F34）
        if msg_type == "plan_approval_response" and sender_agent_id != "lead":
            return Result(
                content="[SendMessage] plan_approval_response 只允许 Lead 发送",
                is_error=True,
            )
        if msg_type == "shutdown_response":
            # shutdown_response 只能发给 Lead
            pass  # 不强制，由 to 地址决定

        # 解析目标
        from nuocode.team.mailbox import Box
        from nuocode.team.mailbox.message import Message

        box = Box(team.mailbox_dir)
        delivered: list[str] = []

        if to == "*":
            # 广播给除发件人外所有成员
            targets = [m for m in team.members if m.agent_id != sender_agent_id]
        else:
            # 按 name 或 agent_id 查找
            member = team.member_by_name(to)
            if member is None:
                # 尝试按 agent_id
                member = team.member_by_agent_id(to)
            if member is None and self._manager.registry is not None:
                agent_id = self._manager.registry.resolve(to)
                if agent_id:
                    member = team.member_by_agent_id(agent_id)
            if member is None:
                return Result(
                    content=f"[SendMessage] 找不到目标成员: {to!r}",
                    is_error=True,
                )
            targets = [member]

        now = int(time.time())
        for member in targets:
            msg = Message(
                from_=sender_agent_id,
                to=member.agent_id,
                type=msg_type,
                summary=summary or message[:50],
                content=message,
                payload=payload,
                timestamp=now,
            )
            try:
                await box.write(member.agent_id, msg)
                delivered.append(member.agent_id)

                # 唤醒 Pane 后端
                if str(member.backend_type) != "in-process" and member.pane_id:
                    try:
                        from nuocode.team.backend import new_backend
                        backend = new_backend(member.backend_type, task_mgr=self._manager.task_mgr)
                        await backend.wake(member.pane_id, member.agent_id)
                    except Exception:  # noqa: BLE001
                        pass

                # 续写检测：in-process 且已 stop（T31/F46）
                elif str(member.backend_type) == "in-process":
                    await self._try_resume(member, team, message or summary)

            except Exception as e:  # noqa: BLE001
                return Result(
                    content=f"[SendMessage] 发送给 {member.agent_id!r} 失败: {e}",
                    is_error=True,
                )

        return Result(
            content=json.dumps(
                {"delivered_to": delivered, "timestamp": now},
                ensure_ascii=False,
            )
        )

    async def _try_resume(self, member: Any, team: Any, message: str) -> None:
        """in-process 队员续写（F46）。"""
        task_mgr = self._manager.task_mgr
        if task_mgr is None:
            return

        bg = task_mgr.get(member.agent_id)
        if bg is None or not bg.is_terminal:
            return  # 还在跑，不需要续派

        # 从 session_dir 恢复（简化：直接续派，Conv 已在 sub_agent 内）
        try:
            await team.set_member_active(member.name, True)
            await task_mgr.send_message(member.name, message)
        except Exception:  # noqa: BLE001
            pass

    def _get_team(self, ctx: Any) -> Any:
        """从 ctx 取 Team，或 active team。"""
        from nuocode.agent.team_hook import teammate_context_from_ctx
        tc = teammate_context_from_ctx(ctx)
        if tc is not None:
            return self._manager.get(tc.team_name)
        # Lead 或主 Agent：使用第一个 Team
        teams = self._manager.list_()
        return teams[0] if teams else None
