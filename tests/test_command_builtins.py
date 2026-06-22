"""builtins 单测：13 条注册 + 关键 handler 行为。"""

from __future__ import annotations

import asyncio

from nuocode.command import NopUI, Registry, register_builtins
from nuocode.command.builtin_local import handle_status
from nuocode.command.builtin_prompt import handle_do
from nuocode.command.builtin_ui import handle_compact, handle_plan
from nuocode.permission import Mode

EXPECTED_NAMES = [
    "clear",
    "compact",
    "do",
    "exit",
    "help",
    "hooks",
    "memory",
    "permission",
    "plan",
    "resume",
    "session",
    "skill",
    "status",
]


def test_register_builtins_all_registered() -> None:
    reg = Registry()
    register_builtins(reg)
    cmds = reg.visible()
    assert len(cmds) == 13
    assert [c.name for c in cmds] == EXPECTED_NAMES
    for n in EXPECTED_NAMES:
        assert reg.lookup(n) is not None


def test_register_builtins_no_collision() -> None:
    reg = Registry()
    register_builtins(reg)  # 不抛即可


class RecordingUI(NopUI):
    def __init__(self) -> None:
        super().__init__()
        self.printed: list[str] = []
        self.errors: list[str] = []
        self.mode_set: list[Mode] = []
        self.injected: list[tuple[str, str]] = []
        self.force_compact_called = 0
        self.resume_opened = 0
        self.cleared = 0
        self.quit_called = 0
        self._idle = True

    def println(self, msg: str) -> None:
        self.printed.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def set_mode(self, m: Mode) -> None:
        self.mode_set.append(m)
        self.mode = m

    def inject_and_send(self, label: str, preset: str) -> None:
        self.injected.append((label, preset))

    def force_compact(self) -> None:
        self.force_compact_called += 1

    def open_resume_menu(self) -> None:
        self.resume_opened += 1

    def clear_and_new_session(self) -> None:
        self.cleared += 1

    def quit(self) -> None:
        self.quit_called += 1

    def idle(self) -> bool:
        return self._idle


def test_handle_status_prints_all_keys() -> None:
    ui = RecordingUI()
    asyncio.run(handle_status(ui))
    assert len(ui.printed) == 1
    text = ui.printed[0]
    for key in ["Mode:", "Tokens:", "Tools:", "Memories:", "Model:", "Directory:"]:
        assert key in text


def test_handle_compact_blocks_when_busy() -> None:
    ui = RecordingUI()
    ui._idle = False
    asyncio.run(handle_compact(ui))
    assert ui.force_compact_called == 0
    assert any("等待" in m for m in ui.errors)


def test_handle_compact_runs_when_idle() -> None:
    ui = RecordingUI()
    asyncio.run(handle_compact(ui))
    assert ui.force_compact_called == 1


def test_handle_do_sets_mode_and_injects() -> None:
    ui = RecordingUI()
    asyncio.run(handle_do(ui))
    assert ui.mode_set == [Mode.DEFAULT]
    assert len(ui.injected) == 1
    label, preset = ui.injected[0]
    assert label == "/do"
    assert preset  # EXECUTE_DIRECTIVE 非空


def test_handle_review_injects_review_directive() -> None:
    # chap11: /review 已迁移为 Skill，不再有内置 handler。
    return


def test_handle_plan_sets_mode_plan() -> None:
    ui = RecordingUI()
    asyncio.run(handle_plan(ui))
    assert ui.mode_set == [Mode.PLAN]


def test_register_builtins_handlers_run_on_nop_ui() -> None:
    """每条命令的 handler 在 NopUI 上 await 不抛。"""
    reg = Registry()
    register_builtins(reg)
    nop = NopUI()
    for cmd in reg.visible():
        asyncio.run(cmd.handler(nop))


def test_help_handler_lists_all_12_names() -> None:
    reg = Registry()
    register_builtins(reg)
    ui = RecordingUI()
    help_cmd = reg.lookup("help")
    assert help_cmd is not None
    asyncio.run(help_cmd.handler(ui))
    assert len(ui.printed) == 1
    text = ui.printed[0]
    for n in EXPECTED_NAMES:
        assert f"/{n}" in text
