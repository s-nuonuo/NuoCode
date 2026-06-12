"""nuocode Textual App：状态机 + 渲染 + 流式 + 选择。"""

from __future__ import annotations

import asyncio
import os
import time
from enum import Enum

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.timer import Timer
from textual.widgets import OptionList, RichLog, Static, TextArea
from textual.widgets.option_list import Option

from nuocode import __version__
from nuocode.config import ProviderConfig
from nuocode.conversation import Conversation
from nuocode.llm import Provider, new_provider
from nuocode.prompt import render_banner
from nuocode.tui.view import (
    assistant_block,
    error_block,
    status_line,
    user_block,
)


class SessionState(Enum):
    SELECTING = "selecting"
    IDLE = "idle"
    STREAMING = "streaming"


class _ChatInput(TextArea):
    """多行输入：Enter 提交、Alt+Enter 插入换行。"""

    BINDINGS = [
        Binding("enter", "submit", "Submit", show=False, priority=True),
        Binding("alt+enter", "newline", "Newline", show=False, priority=True),
    ]

    def action_submit(self) -> None:
        text = self.text
        if not text.strip():
            return
        # 通过 App 调度 submit
        app = self.app
        if isinstance(app, NuoCodeApp):
            self.clear()
            app.post_submit(text)

    def action_newline(self) -> None:
        self.insert("\n")


class NuoCodeApp(App):
    """nuocode 主应用。"""

    CSS = """
    Screen {
        layout: vertical;
    }
    #log {
        height: 1fr;
        border: none;
        padding: 0 1;
    }
    #streaming {
        height: auto;
        min-height: 0;
        padding: 0 1;
        color: $text;
    }
    #input {
        height: 5;
        border: round $accent;
        padding: 0 1;
    }
    #statusbar {
        height: 1;
        background: $boost;
        padding: 0 1;
    }
    #select {
        height: 1fr;
        border: round $accent;
        padding: 1 2;
    }
    .hidden {
        display: none;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
    ]

    def __init__(self, providers: list[ProviderConfig]) -> None:
        super().__init__()
        self.providers: list[ProviderConfig] = providers
        self.provider: Provider | None = None
        self.conv: Conversation = Conversation()
        self.state: SessionState = SessionState.IDLE
        self.cur_reply: str = ""
        self.turn_start: float = 0.0
        self._stream_task: asyncio.Task[None] | None = None
        self._timer: Timer | None = None

    # ───────── compose ─────────

    def compose(self) -> ComposeResult:
        yield RichLog(id="log", wrap=True, markup=False, highlight=False)
        yield Static("", id="streaming")
        # 选择列表（多 provider 时使用）
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

    # ───────── lifecycle ─────────

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
        self._refresh_statusbar()

    def _refresh_statusbar(self) -> None:
        bar = self.query_one("#statusbar", Static)
        if self.provider is None:
            bar.update("")
            return
        bar.update(status_line(self.provider.name, self.provider.model))

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
        if self.state is not SessionState.SELECTING:
            return
        opt_id = event.option.id
        if opt_id is None:
            return
        try:
            idx = int(opt_id)
        except ValueError:
            return
        self._activate_provider(idx)
        self._enter_idle()

    # ───────── submit / streaming ─────────

    def post_submit(self, text: str) -> None:
        """从 _ChatInput 调度的入口（同步）。"""
        if self.state is not SessionState.IDLE:
            return
        if text.strip() == "/exit":
            self.exit()
            return
        if self.provider is None:
            return

        log = self.query_one("#log", RichLog)
        log.write(user_block(text))
        self.conv.add_user(text)

        self.cur_reply = ""
        self.turn_start = time.monotonic()
        self.state = SessionState.STREAMING
        self._refresh_streaming_view()
        self._timer = self.set_interval(0.1, self._tick)
        self._stream_task = asyncio.create_task(self._consume_stream())

    def _tick(self) -> None:
        if self.state is SessionState.STREAMING:
            self._refresh_streaming_view()

    def _refresh_streaming_view(self) -> None:
        elapsed = max(0, int(time.monotonic() - self.turn_start))
        body = self.cur_reply if self.cur_reply else ""
        prefix = "● "
        footer = f"\n\n[Imagining… ({elapsed}s)]"
        self.query_one("#streaming", Static).update(f"{prefix}{body}{footer}")

    async def _consume_stream(self) -> None:
        assert self.provider is not None
        try:
            async for ev in self.provider.stream(self.conv.messages()):
                if ev.err is not None:
                    self._finish_with_error(ev.err)
                    return
                if ev.text:
                    self.cur_reply += ev.text
                    self._refresh_streaming_view()
                if ev.done:
                    self._finish_with_assistant(self.cur_reply)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self._finish_with_error(e)

    def _finish_with_assistant(self, reply: str) -> None:
        log = self.query_one("#log", RichLog)
        if reply:
            log.write(assistant_block(reply))
            self.conv.add_assistant(reply)
        else:
            log.write(error_block(RuntimeError("(empty reply)")))
        self._reset_streaming()

    def _finish_with_error(self, err: BaseException) -> None:
        self.query_one("#log", RichLog).write(error_block(err))
        self._reset_streaming()

    def _reset_streaming(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._stream_task = None
        self.cur_reply = ""
        self.query_one("#streaming", Static).update("")
        self.state = SessionState.IDLE
        self.query_one("#input", _ChatInput).focus()

    # ───────── quit ─────────

    async def action_quit(self) -> None:
        if self._stream_task is not None and not self._stream_task.done():
            self._stream_task.cancel()
        self.exit()
