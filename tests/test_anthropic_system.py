"""守护回归：Anthropic 序列化 system 列表中——
稳定块带 ``cache_control``、环境块不带。
"""

from __future__ import annotations

from nuocode.llm.anthropic_provider import _build_system_blocks


def test_stable_block_has_cache_control() -> None:
    blocks = _build_system_blocks("STABLE", "ENV")
    assert len(blocks) == 2
    assert blocks[0]["type"] == "text"
    assert blocks[0]["text"] == "STABLE"
    assert blocks[0].get("cache_control") == {"type": "ephemeral"}
    # 环境块不带 cache_control
    assert blocks[1]["text"] == "ENV"
    assert "cache_control" not in blocks[1]


def test_only_stable() -> None:
    blocks = _build_system_blocks("S", "")
    assert len(blocks) == 1
    assert blocks[0]["text"] == "S"
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_only_environment() -> None:
    blocks = _build_system_blocks("", "E")
    assert len(blocks) == 1
    assert blocks[0]["text"] == "E"
    assert "cache_control" not in blocks[0]


def test_empty() -> None:
    assert _build_system_blocks("", "") == []
