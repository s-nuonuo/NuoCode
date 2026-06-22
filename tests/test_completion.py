"""CompletionMenu 单测：激活、过滤、上下移、隐藏、render。"""

from __future__ import annotations

from nuocode.command import Command, Kind, Registry, register_builtins
from nuocode.tui.complete import MAX_ROWS, CompletionMenu


async def _noop(ui) -> None:  # noqa: ANN001
    return None


def _full_reg() -> Registry:
    reg = Registry()
    register_builtins(reg)
    return reg


def test_menu_inactive_when_not_slash() -> None:
    m = CompletionMenu()
    m.update("hello", _full_reg())
    assert not m.active
    m.update("", _full_reg())
    assert not m.active


def test_menu_activates_on_slash_with_all_12() -> None:
    m = CompletionMenu()
    m.update("/", _full_reg())
    assert m.active
    assert len(m.items) == 12


def test_menu_filters_by_prefix_s() -> None:
    m = CompletionMenu()
    m.update("/s", _full_reg())
    assert m.active
    names = [c.name for c in m.items]
    assert names == ["session", "status"]


def test_menu_no_match_shows_empty_active() -> None:
    m = CompletionMenu()
    m.update("/zzz", _full_reg())
    assert m.active
    assert m.items == []
    assert m.selected() is None


def test_menu_move_cursor() -> None:
    m = CompletionMenu()
    m.update("/", _full_reg())
    assert m.cursor == 0
    m.move_down()
    assert m.cursor == 1
    m.move_up()
    m.move_up()
    assert m.cursor == len(m.items) - 1  # wrap


def test_menu_hide_clears_state() -> None:
    m = CompletionMenu()
    m.update("/", _full_reg())
    m.hide()
    assert not m.active
    assert m.items == []
    assert m.cursor == 0


def test_menu_multiline_input_disables() -> None:
    m = CompletionMenu()
    m.update("/help\nfoo", _full_reg())
    assert not m.active


def test_menu_render_inactive_empty() -> None:
    m = CompletionMenu()
    assert m.render() == ""


def test_menu_render_highlights_cursor() -> None:
    m = CompletionMenu()
    m.update("/s", _full_reg())
    out = m.render()
    lines = out.splitlines()
    # 第一项被高亮（"> "）
    assert lines[0].startswith("> /session")


def test_menu_scroll_when_overflow() -> None:
    """构造 12 条命令场景下，cursor 推到最末时上方应有"more"提示。"""
    m = CompletionMenu()
    m.update("/", _full_reg())
    # 12 条 > MAX_ROWS=8, 推到末尾
    for _ in range(11):
        m.move_down()
    out = m.render()
    assert m.cursor == 11
    # 上方溢出
    assert "more" in out


def test_menu_handles_hidden_commands() -> None:
    reg = Registry()
    reg.register(Command(name="visible", description="v", kind=Kind.LOCAL, handler=_noop))
    reg.register(
        Command(name="secret", description="s", kind=Kind.LOCAL, handler=_noop, hidden=True)
    )
    m = CompletionMenu()
    m.update("/", reg)
    assert [c.name for c in m.items] == ["visible"]


def test_max_rows_constant() -> None:
    assert MAX_ROWS == 8
