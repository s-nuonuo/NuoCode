"""Registry 单测：注册、冲突、visible 排序、prefix_match。"""

from __future__ import annotations

import pytest

from nuocode.command import Command, Kind, Registry


async def _noop(ui) -> None:  # noqa: ANN001
    return None


def _cmd(name: str, *aliases: str, hidden: bool = False) -> Command:
    return Command(
        name=name,
        description=f"desc-{name}",
        kind=Kind.LOCAL,
        handler=_noop,
        aliases=list(aliases),
        hidden=hidden,
    )


def test_register_ok() -> None:
    reg = Registry()
    reg.register(_cmd("help"))
    reg.register(_cmd("status"))
    assert reg.lookup("help") is not None
    assert reg.lookup("status") is not None


def test_lookup_case_insensitive() -> None:
    reg = Registry()
    reg.register(_cmd("help"))
    assert reg.lookup("Help") is not None
    assert reg.lookup("HELP") is not None


def test_register_duplicate_name_raises() -> None:
    reg = Registry()
    reg.register(_cmd("help"))
    with pytest.raises(RuntimeError) as ei:
        reg.register(_cmd("help"))
    assert "help" in str(ei.value)


def test_register_duplicate_alias_raises() -> None:
    reg = Registry()
    reg.register(_cmd("foo", "x"))
    with pytest.raises(RuntimeError) as ei:
        reg.register(_cmd("bar", "x"))
    assert "x" in str(ei.value)


def test_register_alias_conflicts_with_name() -> None:
    reg = Registry()
    reg.register(_cmd("foo"))
    with pytest.raises(RuntimeError):
        reg.register(_cmd("bar", "foo"))


def test_visible_sorted() -> None:
    reg = Registry()
    for n in ["status", "help", "do", "compact"]:
        reg.register(_cmd(n))
    names = [c.name for c in reg.visible()]
    assert names == ["compact", "do", "help", "status"]


def test_visible_excludes_hidden() -> None:
    reg = Registry()
    reg.register(_cmd("foo"))
    reg.register(_cmd("bar", hidden=True))
    names = [c.name for c in reg.visible()]
    assert names == ["foo"]
    # 但仍可 dispatch 命中
    assert reg.lookup("bar") is not None


def test_prefix_match() -> None:
    reg = Registry()
    for n in ["status", "session", "help", "compact"]:
        reg.register(_cmd(n))
    out = [c.name for c in reg.prefix_match("/s")]
    assert out == ["session", "status"]
    out_all = [c.name for c in reg.prefix_match("/")]
    assert out_all == ["compact", "help", "session", "status"]
    out_none = [c.name for c in reg.prefix_match("/zzz")]
    assert out_none == []


def test_invalid_name_uppercase_raises() -> None:
    reg = Registry()
    with pytest.raises(RuntimeError):
        reg.register(_cmd("Help"))
