"""memory 子包测试：Store CRUD、Manager 索引合并/截断、update_async 解析。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from nuocode import llm
from nuocode.memory import Manager, Store, UpdateAction


def test_store_create_note(tmp_path: Path) -> None:
    s = Store(str(tmp_path))
    s.apply(
        [
            UpdateAction(
                action="create",
                level="project",
                type="user_preference",
                title="简洁回复",
                slug="terse",
                content="用户偏好简洁回复。",
            )
        ]
    )
    files = sorted(tmp_path.iterdir())
    note_files = [p for p in files if p.suffix == ".md" and p.name != "MEMORY.md"]
    assert len(note_files) == 1
    note = note_files[0]
    text = note.read_text(encoding="utf-8")
    assert "type: user_preference" in text
    assert "简洁回复" in text
    assert "created:" in text and "updated:" in text
    # 索引含对应行
    idx = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "[user_preference] 简洁回复" in idx


def test_store_update_note(tmp_path: Path) -> None:
    s = Store(str(tmp_path))
    s.apply(
        [
            UpdateAction(
                action="create",
                level="project",
                type="project_knowledge",
                title="API 约定",
                slug="api",
                content="旧内容",
            )
        ]
    )
    s.apply(
        [
            UpdateAction(
                action="update",
                level="project",
                type="project_knowledge",
                title="API 约定",
                filename="project_knowledge_api.md",
                content="新内容",
            )
        ]
    )
    note = tmp_path / "project_knowledge_api.md"
    text = note.read_text(encoding="utf-8")
    assert "新内容" in text and "旧内容" not in text


def test_store_delete_note(tmp_path: Path) -> None:
    s = Store(str(tmp_path))
    s.apply(
        [
            UpdateAction(
                action="create",
                level="project",
                type="project_knowledge",
                title="OldThing",
                slug="oldthing",
                content="x",
            )
        ]
    )
    s.apply(
        [
            UpdateAction(
                action="delete",
                level="project",
                filename="project_knowledge_oldthing.md",
            )
        ]
    )
    assert not (tmp_path / "project_knowledge_oldthing.md").exists()
    idx = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "OldThing" not in idx


def test_manager_load_index_order(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    user = tmp_path / "u"
    proj.mkdir()
    user.mkdir()
    (proj / "MEMORY.md").write_text("- [project_knowledge] P — proj\n", encoding="utf-8")
    (user / "MEMORY.md").write_text("- [user_preference] U — user\n", encoding="utf-8")
    m = Manager(str(proj), str(user))
    text = m.load_index()
    assert text.index("项目记忆") < text.index("用户记忆")
    assert "P — proj" in text and "U — user" in text


def test_manager_load_index_truncate(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    user = tmp_path / "u"
    proj.mkdir()
    user.mkdir()
    big = "x" * (30 * 1024)
    (proj / "MEMORY.md").write_text(big, encoding="utf-8")
    m = Manager(str(proj), str(user))
    text = m.load_index()
    assert "(index truncated)" in text
    assert len(text.encode("utf-8")) <= 25 * 1024 + len(b"\n\n(index truncated)\n")


def test_manager_has_memory_signal() -> None:
    msgs = [llm.Message(role=llm.ROLE_USER, content="请记住这件事")]
    assert Manager.has_memory_signal(msgs)
    msgs2 = [llm.Message(role=llm.ROLE_USER, content="今天天气好")]
    assert not Manager.has_memory_signal(msgs2)


class _MockProvider:
    name = "mock"
    model = "m"

    def __init__(self, response: str) -> None:
        self._response = response

    async def stream(self, req: llm.Request) -> AsyncIterator[llm.StreamEvent]:
        yield llm.StreamEvent(text=self._response)
        yield llm.StreamEvent(done=True)


def test_manager_update_async_parses_response(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    user = tmp_path / "u"
    proj.mkdir()
    user.mkdir()
    response = (
        '[{"action":"create","level":"project","type":"project_knowledge",'
        '"title":"T","slug":"t","content":"BODY"}]'
    )
    m = Manager(str(proj), str(user), provider=_MockProvider(response), model="mm")
    msgs = [
        llm.Message(role=llm.ROLE_USER, content="hi"),
        llm.Message(role=llm.ROLE_ASSISTANT, content="hello"),
    ]
    asyncio.run(m.update_async(msgs))
    note = proj / "project_knowledge_t.md"
    assert note.exists()
    assert "BODY" in note.read_text(encoding="utf-8")


def test_manager_update_async_handles_invalid_json(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    user = tmp_path / "u"
    proj.mkdir()
    user.mkdir()
    m = Manager(str(proj), str(user), provider=_MockProvider("not json"), model="mm")
    asyncio.run(m.update_async([llm.Message(role=llm.ROLE_USER, content="hi")]))
    # 主流程不抛错，目录无新建笔记
    files = [p for p in proj.iterdir() if p.suffix == ".md"]
    assert files == []
