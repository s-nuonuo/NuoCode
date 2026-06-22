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
from nuocode.command import Registry as CmdRegistry
from nuocode.command import register_builtins
from nuocode.config import ProviderConfig
from nuocode.conversation import Conversation
from nuocode.llm import Provider, new_provider
from nuocode.permission import Engine, Mode, Outcome
from nuocode.prompt import render_banner
from nuocode.tool import Registry
from nuocode.tui.complete import CompletionMenu
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
        app = self.app
        # APPROVING 时把 Enter 转发给权限确认，避免被 priority binding 吞掉
        if isinstance(app, NuoCodeApp):
            if app.state is SessionState.APPROVING:
                app._update_approving("enter")
                return
            if app.state is not SessionState.IDLE:
                return
        text = self.text
        if not text.strip():
            return
        if isinstance(app, NuoCodeApp):
            self.clear()
            app.post_submit(text)

    def action_newline(self) -> None:
        self.insert("\n")

    def on_key(self, event) -> None:  # noqa: ANN001
        """APPROVING 态下，将按键转给 App 处理，避免 TextArea 自身消费数字/方向键。"""
        app = self.app
        if isinstance(app, NuoCodeApp) and app.state is SessionState.APPROVING:
            if app._update_approving(event.key):
                event.stop()
                event.prevent_default()


class NuoCodeApp(App):
    """nuocode 主应用。"""

    CSS = """
    Screen { layout: vertical; }
    #log { height: 1fr; border: none; padding: 0 1; }
    #streaming { height: auto; min-height: 0; padding: 0 1; color: $text; }
    #input { height: 5; border: round $accent; padding: 0 1; }
    #completion { height: auto; min-height: 0; padding: 0 1; color: $text-muted; }
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
        catalog=None,
        executor=None,
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
        # chap10：slash 命令体系
        self._cmd_registry: CmdRegistry = CmdRegistry()
        register_builtins(self._cmd_registry)
        # chap11：Skill catalog 与 Executor
        self.catalog = catalog
        self.executor = executor
        if catalog is not None:
            from nuocode.command.skills_register import register_skills_as_commands

            register_skills_as_commands(self._cmd_registry, catalog)
        self.completion: CompletionMenu = CompletionMenu()
        self._cwd: str = os.getcwd()

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
        yield Static("", id="completion")
        yield Static("", id="statusbar")

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write(render_banner(__version__, os.getcwd()))
        if len(self.providers) == 1:
            self._activate_provider(0)
            self._enter_idle()
        else:
            self._enter_selecting()
        # chap12: emit SessionStart
        asyncio.create_task(self._emit_session_start())

    # ───────── state transitions ─────────

    def _enter_selecting(self) -> None:
        self.state = SessionState.SELECTING

    async def _emit_session_start(self) -> None:
        """chap12: 向 hook 引擎发送 SessionStart 事件。"""
        he = self.runtime.hook_engine if self.runtime is not None else None
        if he is None:
            return
        from nuocode.hook.event import Event as HookEvent
        payload = {
            "event": "SessionStart",
            "session_id": self.session_id,
            "cwd": str(getattr(getattr(self, "runtime", None), "session", None) and
                       self.runtime.session.sessions_dir or ""),
        }
        result = await he.dispatch(HookEvent.SESSION_START, payload)
        if result.injected_prompts and self.runtime is not None:
            self.runtime.append_reminders(result.injected_prompts)
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
        if self.catalog is not None:
            self.agent.with_catalog(self.catalog)
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

        if text.strip().startswith("/"):
            asyncio.create_task(self._dispatch_and_clear(text))
            return

        log = self.query_one("#log", RichLog)
        log.write(user_block(text))
        # chap12: UserPromptSubmit hook emit（拦截检查后再 add_user + start_turn）
        asyncio.create_task(self._submit_with_hook(text))

    async def _submit_with_hook(self, text: str) -> None:
        """chap12: 在 add_user+start_turn 前先 emit UserPromptSubmit；支持拦截。"""
        log = self.query_one("#log", RichLog)
        he = self.runtime.hook_engine if self.runtime is not None else None
        if he is not None:
            from nuocode.hook.event import Event as HookEvent
            try:
                payload = {
                    "event": "UserPromptSubmit",
                    "prompt": text,
                    "session_id": self.session_id,
                    "cwd": str(getattr(getattr(self, "runtime", None), "session", None) and
                               self.runtime.session.sessions_dir or ""),
                }
                result = await he.dispatch(HookEvent.USER_PROMPT_SUBMIT, payload)
                if result.injected_prompts:
                    self.runtime.append_reminders(result.injected_prompts)
                if result.blocked:
                    log.write(f"● [hook 拦截] {result.blocking_hook_name}: {result.reason}")
                    return  # 不 start_turn
            except Exception as e:  # noqa: BLE001
                pass  # hook 失败不影响主流程
        self.conv.add_user(text)
        self._start_turn()

    async def _dispatch_and_clear(self, text: str) -> None:
        from nuocode.tui.commands import dispatch_slash

        try:
            await dispatch_slash(self, text)
        finally:
            self.completion.hide()
            self._refresh_completion_view()

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
                    # 卸下输入框焦点，使 Enter/方向键/数字键能冒泡到 App.on_key
                    try:
                        self.set_focus(None)
                    except Exception:  # noqa: BLE001
                        pass
                    self._refresh_approving_view()
                    await self._wait_for_approval()
                    # 收到决策后回到 STREAMING
                    self.state = SessionState.STREAMING
                    self.pending = None
                    try:
                        self.query_one("#input", _ChatInput).focus()
                    except Exception:  # noqa: BLE001
                        pass
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
        # chap10: 输入框 + 补全菜单激活时优先消费 ↑/↓/Enter/Tab/Esc
        if self.state is SessionState.IDLE and self.completion.active:
            if self._completion_handle_key(event.key):
                event.stop()
                event.prevent_default()
                return
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

    # ───────── chap10: command UI Protocol 实现 ─────────

    @property
    def cmd_registry(self) -> CmdRegistry:
        return self._cmd_registry

    def _cmd_log(self) -> RichLog:
        return self.query_one("#log", RichLog)

    # 输出
    def println(self, msg: str) -> None:
        self._cmd_log().write(notice_block(msg))

    def error(self, msg: str) -> None:
        self._cmd_log().write(error_block(RuntimeError(msg)))

    # 模式（`mode` 属性已存在，set_mode 用于命令切换）
    def set_mode(self, m: Mode) -> None:
        self.mode = m
        try:
            self._refresh_statusbar()
        except Exception:  # noqa: BLE001
            pass

    # 对话注入
    def inject_and_send(self, display_label: str, preset_prompt: str) -> None:
        log = self._cmd_log()
        log.write(user_block(display_label))
        self.conv.add_user(preset_prompt)
        self._start_turn()

    # 只读查询
    def model_name(self) -> str:
        if self.provider is None:
            return ""
        return getattr(self.provider, "model", "") or ""

    def cwd(self) -> str:
        return self._cwd

    def tool_count(self) -> int:
        return self.registry.count()

    def memory_files(self) -> list[str]:
        if self.mem_mgr is None:
            return []
        try:
            project, user = self.mem_mgr.list_files()
        except Exception:  # noqa: BLE001
            return []
        merged: list[str] = []
        if project:
            merged.extend(project)
        if user:
            # 区分前缀，避免同名混淆
            merged.extend(f"~/{n}" for n in user)
        return merged

    def session_path(self) -> str:
        if self.writer is None:
            return ""
        return getattr(self.writer, "path", "") or ""

    def session_id(self) -> str:
        try:
            return self.runtime.session.session_id
        except Exception:  # noqa: BLE001
            return ""

    # 影响界面动作
    def quit(self) -> None:
        self.exit()

    def force_compact(self) -> None:
        self.start_force_compact()

    def open_resume_menu(self) -> None:
        from nuocode.tui import resume as resume_mod

        resume_mod.begin_resume(self)

    def clear_and_new_session(self) -> None:
        from nuocode.compact import new_session_context
        from nuocode.session import Writer as SessWriter

        # chap12: emit SessionEnd 前（同步调）
        he = self.runtime.hook_engine if self.runtime is not None else None
        if he is not None:
            from nuocode.hook.event import Event as HookEvent
            asyncio.create_task(he.dispatch(HookEvent.SESSION_END, {
                "event": "SessionEnd",
                "session_id": self.session_id,
            }))

        # 关旧 writer
        try:
            if self.writer is not None:
                self.writer.close()
        except Exception:  # noqa: BLE001
            pass

        # 新 session_ctx + writer
        try:
            new_ctx = new_session_context(self._cwd)
            new_writer = SessWriter(new_ctx.session_dir)
            if self.provider is not None:
                new_writer.set_model(getattr(self.provider, "model", ""))
        except Exception as e:  # noqa: BLE001
            self.error(f"新建 session 失败: {e}")
            return

        self.writer = new_writer
        # 重建 conversation 绑定新 writer
        self.conv = Conversation(
            on_append=new_writer.on_append, on_replace=new_writer.on_replace
        )
        # 重置 runtime（含 hook only_once 集合）
        asyncio.create_task(self.runtime.reset_for_new_session(new_ctx))
        self.iter = 0
        self.usage_in = 0
        self.usage_out = 0
        # 清空对话区域
        try:
            self._cmd_log().clear()
            self._refresh_statusbar()
        except Exception:  # noqa: BLE001
            pass

        # chap12: emit SessionStart 新会话
        asyncio.create_task(self._emit_session_start())

    # 状态机查询
    def idle(self) -> bool:
        return self.state is SessionState.IDLE

    # chap11: skills UI 接口
    def list_catalog_skills(self) -> list[tuple[str, str, str]]:
        if self.catalog is None:
            return []
        out: list[tuple[str, str, str]] = []
        for sk in self.catalog.list():
            out.append((sk.meta.name, sk.source.value, sk.meta.description))
        return out

    def list_active_skills(self) -> list[str]:
        return list(self.runtime.active_skills.names())

    def clear_active_skills(self) -> None:
        self.runtime.active_skills.clear()

    def append_assistant_message(self, text: str) -> None:
        self.conv.add_assistant(text)

    def recent_messages(self, n: int) -> list:
        msgs = self.conv.messages()
        return msgs[-n:] if n > 0 else list(msgs)

    def all_messages(self) -> list:
        return list(self.conv.messages())

    # chap12: hooks UI 接口
    def list_hooks(self) -> list[tuple[str, str, str, str]] | None:
        """返回 [(name, event, action_type, source), ...] 或 None（引擎未初始化）。"""
        he = self.runtime.hook_engine if self.runtime is not None else None
        if he is None:
            return None
        return [
            (
                r.name,
                r.event.value,
                r.action.type.value,
                r.source or "",
            )
            for r in he.rules
        ]

    # ───────── chap10: 自动补全键位 ─────────

    def _refresh_completion_view(self) -> None:
        try:
            comp = self.query_one("#completion", Static)
        except Exception:  # noqa: BLE001
            return
        if self.completion.active:
            try:
                width = self.size.width
            except Exception:  # noqa: BLE001
                width = 80
            comp.update(self.completion.render(width))
        else:
            comp.update("")

    def _sync_completion_from_input(self) -> None:
        try:
            ti = self.query_one("#input", _ChatInput)
        except Exception:  # noqa: BLE001
            return
        text = ti.text
        self.completion.update(text, self._cmd_registry)
        self._refresh_completion_view()

    async def _execute_completion_selected(self) -> None:
        sel = self.completion.selected()
        if sel is None:
            self.completion.hide()
            self._refresh_completion_view()
            return
        try:
            ti = self.query_one("#input", _ChatInput)
            ti.clear()
        except Exception:  # noqa: BLE001
            pass
        self.completion.hide()
        self._refresh_completion_view()
        await self._dispatch_and_clear(f"/{sel.name}")

    def on_text_area_changed(self, event) -> None:  # noqa: ANN001
        try:
            if event.text_area.id == "input":
                self._sync_completion_from_input()
        except Exception:  # noqa: BLE001
            pass

    # 旧 `on_key` 仅处理 APPROVING；这里追加补全键位与备份
    def _completion_handle_key(self, key: str) -> bool:
        if not self.completion.active:
            return False
        if key == "up":
            self.completion.move_up()
            self._refresh_completion_view()
            return True
        if key == "down":
            self.completion.move_down()
            self._refresh_completion_view()
            return True
        if key == "escape":
            self.completion.hide()
            self._refresh_completion_view()
            return True
        if key in ("enter", "tab"):
            asyncio.create_task(self._execute_completion_selected())
            return True
        return False
