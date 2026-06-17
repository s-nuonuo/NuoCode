"""session 子包：JSONL 写入、列表、加载、清理测试。"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
from pathlib import Path

from nuocode import llm
from nuocode.session import (
    Writer,
    _truncate_orphaned_tool_calls,
    clean_expired,
    list_sessions,
    load_session,
)


def test_writer_append_and_read(tmp_path: Path) -> None:
    sd = tmp_path / "20260601-120000-abcd"
    w = Writer(str(sd))
    w.append(llm.Message(role="user", content="hi"), model="m1", is_first=True)
    w.append(llm.Message(role="assistant", content="hello"))
    w.append(llm.Message(role="user", content="bye"))
    w.close()
    lines = (sd / "conversation.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    d0 = json.loads(lines[0])
    assert d0["role"] == "user" and d0["content"] == "hi" and d0["model"] == "m1"
    d1 = json.loads(lines[1])
    assert d1["role"] == "assistant" and "model" not in d1


def test_writer_compact_marker_and_load(tmp_path: Path) -> None:
    sd = tmp_path / "20260601-120100-aaaa"
    w = Writer(str(sd))
    w.append(llm.Message(role="user", content="old"), model="m", is_first=True)
    w.append(llm.Message(role="assistant", content="old reply"))
    w.write_compact_marker()
    w.append(llm.Message(role="user", content="new"))
    w.append(llm.Message(role="assistant", content="new reply"))
    w.close()

    msgs = load_session(str(sd))
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[0].content == "new" and msgs[1].content == "new reply"


def test_load_session_bad_line_skip(tmp_path: Path) -> None:
    sd = tmp_path / "20260601-120200-bbbb"
    sd.mkdir(parents=True)
    p = sd / "conversation.jsonl"
    p.write_text(
        '{"role":"user","content":"a","ts":1}\n'
        "{not valid json\n"
        '{"role":"assistant","content":"b","ts":2}\n',
        encoding="utf-8",
    )
    msgs = load_session(str(sd))
    assert [m.content for m in msgs] == ["a", "b"]


def test_load_session_orphaned_tool_calls(tmp_path: Path) -> None:
    sd = tmp_path / "20260601-120300-cccc"
    sd.mkdir(parents=True)
    p = sd / "conversation.jsonl"
    p.write_text(
        '{"role":"user","content":"q","ts":1}\n'
        '{"role":"assistant","content":"call","tool_calls":[{"id":"t1","name":"x","input":"{}"}],"ts":2}\n',
        encoding="utf-8",
    )
    msgs = load_session(str(sd))
    # orphaned assistant with tool_calls 被截断
    assert len(msgs) == 1 and msgs[0].role == "user"


def test_truncate_helper_no_tool_calls() -> None:
    m1 = llm.Message(role="user", content="a")
    m2 = llm.Message(role="assistant", content="b")
    assert _truncate_orphaned_tool_calls([m1, m2]) == [m1, m2]


def test_list_sessions(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    ids = ["20260601-120000-aaaa", "20260601-130000-bbbb", "20260601-140000-cccc"]
    for sid in ids:
        sd = sessions_dir / sid
        w = Writer(str(sd))
        w.append(llm.Message(role="user", content=f"hello {sid}"), model="mx", is_first=True)
        w.close()
    out = list_sessions(str(sessions_dir))
    assert len(out) == 3
    # 按修改时间倒序：最新在前
    assert out[0].modified_at >= out[1].modified_at >= out[2].modified_at
    for info in out:
        assert info.title.startswith("hello")
        assert info.model == "mx"
        assert info.size > 0


def test_list_sessions_skips_old_format(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    # 旧格式
    old = sessions_dir / "1717000000-abc12345"
    old.mkdir()
    (old / "conversation.jsonl").write_text(
        '{"role":"user","content":"x","ts":1}\n', encoding="utf-8"
    )
    # 新格式
    new = sessions_dir / "20260601-120000-aaaa"
    Writer(str(new)).append(llm.Message(role="user", content="hello"), model="m", is_first=True)
    out = list_sessions(str(sessions_dir))
    assert len(out) == 1
    assert out[0].id == "20260601-120000-aaaa"


def test_clean_expired(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    # 31 天前
    long_ago = _dt.datetime.now() - _dt.timedelta(days=31)
    expired_id = long_ago.strftime("%Y%m%d-%H%M%S") + "-dead"
    (sessions_dir / expired_id).mkdir()
    # 1 天前
    recent = _dt.datetime.now() - _dt.timedelta(days=1)
    recent_id = recent.strftime("%Y%m%d-%H%M%S") + "-live"
    (sessions_dir / recent_id).mkdir()
    # 旧格式
    old_fmt = sessions_dir / "1717000000-abc12345"
    old_fmt.mkdir()

    asyncio.run(clean_expired(str(sessions_dir), _dt.timedelta(days=30)))
    remaining = {p.name for p in sessions_dir.iterdir()}
    assert expired_id not in remaining
    assert recent_id in remaining
    assert "1717000000-abc12345" in remaining
