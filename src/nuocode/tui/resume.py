"""TUI 会话恢复：列表展示 + 选择 + 加载。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from textual.widgets import OptionList, RichLog
from textual.widgets.option_list import Option

from nuocode import session as session_mod
from nuocode.compact.state import open_session_context
from nuocode.conversation import Conversation
from nuocode.session.list import SessionInfo

if TYPE_CHECKING:
    from nuocode.tui.app import NuoCodeApp

logger = logging.getLogger(__name__)

RESUME_LIST_ID = "resume_list"
TIME_GAP_THRESHOLD_SEC = 6 * 3600
TIME_GAP_REMINDER = (
    "[系统提示] 本会话已暂停 {dur}。部分上下文可能已过时，如需最新信息请重新读取相关文件。"
)


def _human_time_ago(dt: datetime) -> str:
    delta = datetime.now() - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / 1024 / 1024:.1f}MB"


def _format_item(info: SessionInfo) -> str:
    title = info.title or "(empty)"
    return f"{title} · {_human_time_ago(info.modified_at)} · {info.model or '?'} · {_human_size(info.size)}"


def begin_resume(app: NuoCodeApp) -> None:
    """进入会话选择列表。"""
    from nuocode.tui.app import SessionState

    sessions_dir = app.sessions_dir
    items = session_mod.list_sessions(sessions_dir)
    log = app.query_one("#log", RichLog)
    if not items:
        log.write("● 没有找到可恢复的会话。")
        return

    # 复用现有的 #select OptionList
    select = app.query_one("#select", OptionList)
    select.clear_options()
    for i, info in enumerate(items):
        select.add_option(Option(_format_item(info), id=f"resume:{i}"))
    app._resume_items = items  # 暂存供选中后取
    select.display = True
    app.query_one("#input").display = False
    select.focus()
    app.state = SessionState.RESUMING
    app.query_one("#statusbar").update("请选择要恢复的会话（Enter 确认 / Esc 取消）")


async def do_resume_session(app: NuoCodeApp, info: SessionInfo) -> None:
    """加载选中会话，替换 app 的 conv / writer / ses_ctx。"""
    log = app.query_one("#log", RichLog)
    log.write(f"● 正在恢复会话 {info.id}...")
    msgs = session_mod.load_session(info.dir)
    if not msgs:
        log.write("● 该会话为空，已取消恢复。")
        return

    # 时间跨度提醒
    try:
        last_mtime = info.modified_at
        if (datetime.now() - last_mtime).total_seconds() > TIME_GAP_THRESHOLD_SEC:
            from nuocode import llm

            secs = int((datetime.now() - last_mtime).total_seconds())
            if secs >= 86400:
                dur = f"{secs // 86400} 天"
            elif secs >= 3600:
                dur = f"{secs // 3600} 小时"
            else:
                dur = f"{secs // 60} 分钟"
            msgs.append(llm.Message(role=llm.ROLE_USER, content=TIME_GAP_REMINDER.format(dur=dur)))
    except Exception:  # noqa: BLE001
        pass

    # 替换 writer
    try:
        if app.writer is not None:
            app.writer.close()
    except Exception:  # noqa: BLE001
        pass
    new_writer = session_mod.Writer.open_existing(info.dir)
    new_writer.set_model(app.provider.model if app.provider else "")
    app.writer = new_writer

    # 重建 conv（绑定新 writer 回调）
    new_conv = Conversation.from_messages(
        msgs, on_append=new_writer.on_append, on_replace=new_writer.on_replace
    )
    app.conv = new_conv

    # 替换 ses_ctx
    import os

    workspace = os.getcwd()
    new_ctx = open_session_context(workspace, info.id)
    app.runtime.session = new_ctx
    # 确保 spill_dir 存在
    try:
        import pathlib

        pathlib.Path(new_ctx.spill_dir).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    log.write(f"● 已恢复会话 {info.id}，共 {len(msgs)} 条消息")

    # chap12: emit SessionResume
    he = getattr(app.runtime, "hook_engine", None)
    if he is not None:
        from nuocode.hook.event import Event as HookEvent
        try:
            result = await he.dispatch(HookEvent.SESSION_RESUME, {
                "event": "SessionResume",
                "session_id": info.id,
            })
            if result.injected_prompts:
                app.runtime.append_reminders(result.injected_prompts)
        except Exception:  # noqa: BLE001
            pass


def handle_resume_selection(app: NuoCodeApp, opt_id: str) -> None:
    """OptionList Enter 选择回调（id 形如 ``resume:N``）。"""
    if not opt_id.startswith("resume:"):
        return
    try:
        idx = int(opt_id.split(":", 1)[1])
    except ValueError:
        return
    items: list[SessionInfo] = getattr(app, "_resume_items", [])
    if idx < 0 or idx >= len(items):
        return
    info = items[idx]
    asyncio.create_task(_finish_resume(app, info))


async def _finish_resume(app: NuoCodeApp, info: SessionInfo) -> None:
    try:
        await do_resume_session(app, info)
    finally:
        from nuocode.tui.app import SessionState

        # 退出 resume 列表，回到 idle
        try:
            app.query_one("#select").display = False
            app.query_one("#input").display = True
            app.query_one("#input").focus()
        except Exception:  # noqa: BLE001
            pass
        app.state = SessionState.IDLE
        app._refresh_statusbar()


def cancel_resume(app: NuoCodeApp) -> None:
    from nuocode.tui.app import SessionState

    try:
        app.query_one("#select").display = False
        app.query_one("#input").display = True
        app.query_one("#input").focus()
    except Exception:  # noqa: BLE001
        pass
    app.state = SessionState.IDLE
    app._refresh_statusbar()


__all__ = [
    "begin_resume",
    "cancel_resume",
    "do_resume_session",
    "handle_resume_selection",
]
