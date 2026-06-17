"""nuocode Textual App：状态机 + 渲染 + 流式 + 选择 + 权限五层（chap04/06）。"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from enum import Enum

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.timer import Timer
from textual.widgets import OptionList, RichLog, Static, TextArea
from textual.widgets.option_list import Option

from nuocode import __version__
from nuocode.agent import Agent, ApprovalRequest, Phase
from nuocode.agent.runtime import SessionRuntime
from nuocode.config import ProviderConfig
from nuocode.conversation import Conversation
from nuocode.llm import Provider, new_provider
from nuocode.permission import Engine, Mode, Outcome
from nuocode.prompt import render_banner
from nuocode.tool import Registry
from nuocode.tui.view import (
    approval_block,
    assistant_block,
    error_block,
    notice_block,
    status_line,
    tool_line,
    tool_result_summary,
    user_block,
)


class SessionState(Enum):
    SELECTING = "selecting"
    IDLE = "idle"
    STREAMING = "streaming"
    APPROVING = "approving"
    RESUMING = "resuming"


@dataclass
class _ToolDisplay:
    name: str
    args: str


def next_mode(m: Mode) -> Mode:
    """循环：DEFAULT → ACCEPT_EDITS → PLAN → BYPASS → DEFAULT。"""
    return Mode((int(m) + 1) % 4)


def outcome_for_index(idx: int) -> Outcome:
    """0=ALLOW_ONCE, 1=ALLOW_FOREVER, 2=DENY_ONCE。"""
    if idx == 0:
        return Outcome.ALLOW_ONCE
    if idx == 1:
        return Outcome.ALLOW_FOREVER
    return Outcome.DENY_ONCE


class _ChatInput(TextArea):
    BINDINGS = [
        Binding("enter", "submit", "Submit", show=False, priority=True),
        Binding("alt+enter", "newline", "Newline", show=False, priority=True),
    ]

    def action_submit(self) -> None:
        text = self.text
        if not text.strip():
            return
        app = self.app
        if isinstance(app, NuoCodeApp):
            self.clear()
            app.post_submit(text)

    def action_newline(self) -> None:
        self.insert("\n")


class NuoCodeApp(App):
    """nuocode 主应用。"""

    CSS = """
    Screen { layout: vertical; }
    #log { height: 1fr; border: none; padding: 0 1; }
    #streaming { height: auto; min-height: 0; padding: 0 1; color: $text; }
    #input { height: 5; border: round $accent; padding: 0 1; }
    #statusbar { height: 1; background: $boost; padding: 0 1; }
    #select { height: 1fr; border: round $accent; padding: 1 2; }
    .hidden { display: none; }
    """

    BINDINGS = [
        Binding("ctrl+c", "ctrl_c", "Quit/Cancel", priority=True),
        Binding("escape", "esc", "Cancel", priority=True, show=False),
        Binding("shift+tab", "cycle_mode", "Mode", priority=True, show=False),
    ]

    def __init__(
        self,
        providers: list[ProviderConfig],
        registry: Registry,
        engine: Engine,
        runtime: SessionRuntime | None = None,
        writer=None,
        mem_mgr=None,
        instruction_text: str = "",
        memory_text: str = "",
        sessions_dir: str = "",
    ) -> None:
        super().__init__()
        self.providers: list[ProviderConfig] = providers
        self.registry: Registry = registry
        self.engine: Engine = engine
        if runtime is None:
            import tempfile

            from nuocode.compact import new_session_context

            runtime = SessionRuntime(session=new_session_context(tempfile.gettempdir()))
        self.runtime: SessionRuntime = runtime
        self.writer = writer
        self.mem_mgr = mem_mgr
        self.instruction_text = instruction_text
        self.memory_text = memory_text
        self.sessions_dir = sessions_dir
        self.provider: Provider | None = None
        self.agent: Agent | None = None
        if writer is not None:
            self.conv: Conversation = Conversation(
                on_append=writer.on_append, on_replace=writer.on_replace
            )
        else:
            self.conv = Conversation()
        self._resume_items: list = []
        self.state: SessionState = SessionState.IDLE
        self.cur_reply: str = ""
        self.turn_start: float = 0.0
        self.cur_tools: list[_ToolDisplay] = []
        self._stream_task: asyncio.Task[None] | None = None
        self._timer: Timer | None = None
        # chap04 / 06
        self.mode: Mode = engine.start_mode()
        self.iter: int = 0
        self.usage_in: int = 0
        self.usage_out: int = 0
        self.turn_cancel: asyncio.Event | None = None
        # chap06：人在回路
        self.pending: ApprovalRequest | None = None
        self.approve_cursor: int = 0

    # ───────── compose ─────────

    def compose(self) -> ComposeResult:
        yield RichLog(id="log", wrap=True, markup=False, highlight=False)
        yield Static("", id="streaming")
        options = [
            Option(f"{p.name}  ({p.model})", id=str(i)) for i, p in enumerate(self.providers)
        ]
        select = OptionList(*options, id="select")
        select.display = False
        yield select
        ta = _ChatInput(id="input")
        ta.show_line_numbers = False
        yield ta
        yield Static("", id="statusbar")

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write(render_banner(__version__, os.getcwd()))
        if len(self.providers) == 1:
            self._activate_provider(0)
            self._enter_idle()
        else:
            self._enter_selecting()

    # ───────── state transitions ─────────

    def _enter_selecting(self) -> None:
        self.state = SessionState.SELECTING
        self.query_one("#select", OptionList).display = True
        self.query_one("#input", _ChatInput).display = False
        self.query_one("#streaming", Static).update("")
        self.query_one("#statusbar", Static).update("请使用方向键选择一个 provider，按 Enter 确认")
        self.query_one("#select", OptionList).focus()

    def _activate_provider(self, index: int) -> None:
        cfg = self.providers[index]
        self.provider = new_provider(cfg)
        self.agent = Agent(
            self.provider,
            self.registry,
            __version__,
            self.engine,
            self.runtime,
            cfg.effective_context_window(),
            memory_manager=self.mem_mgr,
            instruction_text=self.instruction_text,
            memory_text=self.memory_text,
        )
        # 将 model 名推送给 writer，以便首条消息带 model 字段
        if self.writer is not None:
            self.writer.set_model(cfg.model)
        # provider 选定后绑定给记忆管理器
        if self.mem_mgr is not None:
            self.mem_mgr.set_provider(self.provider, cfg.model)
        self._refresh_statusbar()

    def _refresh_statusbar(self) -> None:
        bar = self.query_one("#statusbar", Static)
        if self.provider is None:
            bar.update("")
            return
        bar.update(
            status_line(
                self.mode,
                self.provider.model,
                usage_in=self.usage_in,
                usage_out=self.usage_out,
            )
        )

    def _enter_idle(self) -> None:
        self.state = SessionState.IDLE
        self.query_one("#select", OptionList).display = False
        ti = self.query_one("#input", _ChatInput)
        ti.display = True
        ti.focus()
        self.query_one("#streaming", Static).update("")
        self._refresh_statusbar()

    # ───────── select handler ─────────

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        opt_id = event.option.id
        if opt_id is None:
            return
        # /resume 列表：opt_id 形如 ``resume:N``
        if (
            self.state is SessionState.RESUMING
            and isinstance(opt_id, str)
            and opt_id.startswith("resume:")
        ):
            from nuocode.tui import resume as resume_mod

            resume_mod.handle_resume_selection(self, opt_id)
            return
        if self.state is not SessionState.SELECTING:
            return
        try:
            idx = int(opt_id)
        except ValueError:
            return
        self._activate_provider(idx)
        self._enter_idle()

    # ───────── submit / streaming ─────────

    def post_submit(self, text: str) -> None:
        if self.state is not SessionState.IDLE:
            return
        if self.agent is None:
            return

        from nuocode.tui import commands as cmd_mod

        if cmd_mod.is_command(text):
            cmd_mod.dispatch(self, text)
            return

        log = self.query_one("#log", RichLog)
        log.write(user_block(text))
        self.conv.add_user(text)
        self._start_turn()

    def start_force_compact(self) -> None:
        """``/compact`` 命令入口：以异步任务跑 ``Agent.run_force_compact``。"""
        if self.agent is None or self.state is not SessionState.IDLE:
            return
        asyncio.create_task(self._do_force_compact())

    async def _do_force_compact(self) -> None:
        assert self.agent is not None
        log = self.query_one("#log", RichLog)
        try:
            async for ev in self.agent.run_force_compact(self.conv):
                if ev.err is not None:
                    log.write(error_block(ev.err))
                    continue
                if ev.compact is not None:
                    log.write(
                        f"● [compact:{ev.compact.trigger}] "
                        f"{ev.compact.before_tokens} → {ev.compact.after_tokens} tokens"
                    )
                if ev.notice:
                    log.write(f"● {ev.notice}")
        except Exception as e:  # noqa: BLE001
            log.write(error_block(e))

    def _start_turn(self) -> None:
        self.cur_reply = ""
        self.cur_tools = []
        self.iter = 0
        self.turn_start = time.monotonic()
        self.turn_cancel = asyncio.Event()
        self.state = SessionState.STREAMING
        self._refresh_streaming_view()
        self._timer = self.set_interval(0.1, self._tick)
        self._stream_task = asyncio.create_task(self._consume_agent_events())

    def _tick(self) -> None:
        if self.state is SessionState.STREAMING:
            self._refresh_streaming_view()

    def _refresh_streaming_view(self) -> None:
        elapsed = max(0, int(time.monotonic() - self.turn_start))
        body = self.cur_reply if self.cur_reply else ""
        prefix = "● "
        if self.cur_tools:
            lines = [f"[{i + 1}] Running {t.name}({t.args})…" for i, t in enumerate(self.cur_tools)]
            label = "\n".join(lines) + f"\n({elapsed}s · 第 {self.iter} 轮)"
        else:
            extra = f" · 第 {self.iter} 轮" if self.iter > 0 else ""
            label = f"Imagining… ({elapsed}s{extra})"
        footer = f"\n\n[{label}]"
        self.query_one("#streaming", Static).update(f"{prefix}{body}{footer}")

    def _refresh_approving_view(self) -> None:
        if self.pending is None:
            return
        self.query_one("#streaming", Static).update(
            approval_block(
                self.pending.name,
                self.pending.args,
                self.pending.reason,
                self.approve_cursor,
            )
        )

    async def _consume_agent_events(self) -> None:
        assert self.agent is not None
        log = self.query_one("#log", RichLog)
        try:
            assert self.turn_cancel is not None
            async for ev in self.agent.run(self.conv, self.mode, self.turn_cancel):
                if ev.err is not None:
                    log.write(error_block(ev.err))
                    continue
                if ev.approval is not None:
                    # 进入 APPROVING 态，等待用户三选一
                    self.pending = ev.approval
                    self.approve_cursor = 0
                    self.state = SessionState.APPROVING
                    self._refresh_approving_view()
                    await self._wait_for_approval()
                    # 收到决策后回到 STREAMING
                    self.state = SessionState.STREAMING
                    self.pending = None
                    self._refresh_streaming_view()
                    continue
                if ev.tool is not None:
                    if ev.tool.phase is Phase.START:
                        if self.cur_reply.strip():
                            log.write(assistant_block(self.cur_reply))
                            self.cur_reply = ""
                        self.cur_tools.append(_ToolDisplay(ev.tool.name, ev.tool.args))
                        self._refresh_streaming_view()
                    else:
                        if self.cur_tools:
                            self.cur_tools.pop(0)
                        log.write(tool_line(ev.tool.name, ev.tool.args))
                        log.write(tool_result_summary(ev.tool.result, ev.tool.is_error))
                        self._refresh_streaming_view()
                    continue
                if ev.usage is not None:
                    self.usage_in += ev.usage.input
                    self.usage_out += ev.usage.output
                    self._refresh_statusbar()
                if ev.notice:
                    log.write(f"● {ev.notice}")
                if ev.compact is not None:
                    log.write(
                        f"● [compact:{ev.compact.trigger}] "
                        f"{ev.compact.before_tokens} → {ev.compact.after_tokens} tokens"
                    )
                if ev.iter > 0:
                    self.iter = ev.iter
                    self._refresh_streaming_view()
                if ev.text:
                    self.cur_reply += ev.text
                    self._refresh_streaming_view()
                if ev.done:
                    self._finish_with_assistant(self.cur_reply)
                    return
            self._finish_turn()
        except asyncio.CancelledError:
            self._finish_turn()
            raise
        except Exception as e:  # noqa: BLE001
            log.write(error_block(e))
            self._finish_turn()

    async def _wait_for_approval(self) -> None:
        """等待 self.pending.respond 完成（由按键回调 set_result）。"""
        if self.pending is None:
            return
        try:
            await self.pending.respond
        except asyncio.CancelledError:
            raise

    def _finish_with_assistant(self, reply: str) -> None:
        log = self.query_one("#log", RichLog)
        if reply.strip():
            log.write(assistant_block(reply))
        self._finish_turn()

    def _finish_turn(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._stream_task = None
        self.cur_reply = ""
        self.cur_tools = []
        self.iter = 0
        self.turn_cancel = None
        self.pending = None
        try:
            self.query_one("#streaming", Static).update("")
        except Exception:  # noqa: BLE001
            return
        self.state = SessionState.IDLE
        try:
            self._refresh_statusbar()
            self.query_one("#input", _ChatInput).focus()
        except Exception:  # noqa: BLE001
            pass

    # ───────── 按键 ─────────

    def action_ctrl_c(self) -> None:
        self._handle_cancel(exit_if_idle=True)

    def action_esc(self) -> None:
        self._handle_cancel(exit_if_idle=False)

    def _handle_cancel(self, exit_if_idle: bool) -> None:
        if self.state is SessionState.RESUMING:
            from nuocode.tui import resume as resume_mod

            resume_mod.cancel_resume(self)
            return
        if self.state is SessionState.APPROVING and self.pending is not None:
            # 兜底：先解开 future，再走取消
            if not self.pending.respond.done():
                self.pending.respond.set_result(Outcome.DENY_ONCE)
            if self.turn_cancel is not None:
                self.turn_cancel.set()
            return
        if self.state is SessionState.STREAMING and self.turn_cancel is not None:
            self.turn_cancel.set()
            return
        if exit_if_idle:
            self.exit()

    def action_cycle_mode(self) -> None:
        if self.state is not SessionState.IDLE:
            return
        self.mode = next_mode(self.mode)
        try:
            log = self.query_one("#log", RichLog)
            label, _ = __import__("nuocode.tui.view", fromlist=["mode_badge"]).mode_badge(self.mode)
            log.write(notice_block(f"已切换到 {label} 模式"))
        except Exception:  # noqa: BLE001
            pass
        self._refresh_statusbar()

    # ───────── 待批准态按键 ─────────

    def on_key(self, event) -> None:
        if self.state is not SessionState.APPROVING:
            return
        if self.pending is None:
            return
        key = event.key
        handled = self._update_approving(key)
        if handled:
            event.stop()
            event.prevent_default()

    def _update_approving(self, key: str) -> bool:
        if self.pending is None:
            return False
        if key in ("up", "k"):
            self.approve_cursor = (self.approve_cursor - 1) % 3
            self._refresh_approving_view()
            return True
        if key in ("down", "j"):
            self.approve_cursor = (self.approve_cursor + 1) % 3
            self._refresh_approving_view()
            return True
        if key in ("enter", "space"):
            self._submit_outcome(outcome_for_index(self.approve_cursor))
            return True
        if key == "1":
            self._submit_outcome(Outcome.ALLOW_ONCE)
            return True
        if key == "2":
            self._submit_outcome(Outcome.ALLOW_FOREVER)
            return True
        if key == "3":
            self._submit_outcome(Outcome.DENY_ONCE)
            return True
        if key in ("y",):
            self._submit_outcome(Outcome.ALLOW_ONCE)
            return True
        if key in ("n", "d"):
            self._submit_outcome(Outcome.DENY_ONCE)
            return True
        return False

    def _submit_outcome(self, outcome: Outcome) -> None:
        if self.pending is None:
            return
        if not self.pending.respond.done():
            self.pending.respond.set_result(outcome)
