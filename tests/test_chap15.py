"""chap15 Agent Team 测试套件（T33）。

覆盖：
- team/types.py：BackendType、Team、TeammateInfo 序列化
- team/persistence.py：sanitize、atomic_write_json
- team/manager.py：create/get/delete/add_member
- team/mailbox：Box.write / read_unread / mark_read
- team/registry：AgentNameRegistry 双向映射
- team/tasks：Store CRUD + 双向 blocked_by
- tool/filter.py：teammate=True 注入 TEAMMATE_EXTRA_TOOLS
- agent/team_hook.py：TeammateContext with/from ctx
- agent/team_mailbox.py：ingest_team_mailbox
- coordinator/__init__.py：is_enabled 双锁逻辑
- team/backend/detect.py：detect() fallback
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── helpers ──────────────────────────────────────────────────────────────────

def tmp_path() -> Path:
    d = Path(tempfile.mkdtemp())
    return d


# ── team/types.py ─────────────────────────────────────────────────────────────

class TestBackendType:
    def test_values(self):
        from nuocode.team.types import BackendType
        assert BackendType.TMUX == "tmux"
        assert BackendType.ITERM2 == "iterm2"
        assert BackendType.IN_PROCESS == "in-process"


class TestTeamSerialization:
    def test_round_trip(self):
        from nuocode.team.types import BackendType, Team

        team = Team(
            name="my team",
            sanitized_name="my-team",
            lead_agent_id="lead",
            backend=BackendType.IN_PROCESS,
        )
        team.config_path = "/tmp/config.json"
        team.tasks_path = "/tmp/tasks.json"
        team.mailbox_dir = "/tmp/mailbox"

        d = team.to_dict()
        assert d["name"] == "my team"
        assert d["sanitized_name"] == "my-team"
        assert d["backend"] == "in-process"
        assert "_lock" not in d

        team2 = Team.from_dict(d, "/tmp")
        assert team2.name == "my team"
        assert team2.backend == BackendType.IN_PROCESS

    def test_teammate_info_fields(self):
        from nuocode.team.types import TeammateInfo, BackendType
        m = TeammateInfo(
            name="alice",
            agent_id="agent-abc",
            is_active=True,
            backend_type=BackendType.TMUX,
            pane_id="%7",
        )
        d = m.to_dict()
        assert d["name"] == "alice"
        assert d["is_active"] is True
        assert d["pane_id"] == "%7"

        m2 = TeammateInfo.from_dict(d)
        assert m2.name == "alice"
        assert m2.backend_type == BackendType.TMUX


# ── team/persistence.py ───────────────────────────────────────────────────────

class TestSanitize:
    def test_normal(self):
        from nuocode.team.persistence import sanitize
        # 空格和 ! 都变成 -；strip("-") 去掉末尾 -
        result = sanitize("my team!")
        assert "-" in result
        assert result.startswith("my")

    def test_valid(self):
        from nuocode.team.persistence import sanitize
        assert sanitize("my-team_2.0") == "my-team_2.0"

    def test_empty(self):
        from nuocode.team.persistence import sanitize
        assert sanitize("") == ""

    def test_no_leading_trailing_dash(self):
        from nuocode.team.persistence import sanitize
        result = sanitize("---hello---")
        assert not result.startswith("-")
        assert not result.endswith("-")


class TestAtomicWrite:
    def test_write_and_read(self):
        from nuocode.team.persistence import atomic_write_json, read_json
        p = tmp_path() / "test.json"
        data = {"key": "value", "num": 42}
        atomic_write_json(str(p), data)
        result = read_json(str(p))
        assert result == data


# ── team/manager.py ───────────────────────────────────────────────────────────

class TestManagerCreate:
    def test_create_basic(self):
        from nuocode.team.manager import Manager

        home = tmp_path()
        root = tmp_path()

        async def _run():
            mgr = Manager(home_dir=home, project_root=root)
            team = await mgr.create("test team")
            assert team.lead_agent_id == "lead"
            assert len(team.members) == 1
            assert team.members[0].name == "lead"

        asyncio.run(_run())

    def test_create_duplicate_suffix(self):
        from nuocode.team.manager import Manager

        home = tmp_path()
        root = tmp_path()

        async def _run():
            mgr = Manager(home_dir=home, project_root=root)
            t1 = await mgr.create("alpha")
            t2 = await mgr.create("alpha")
            assert t1.sanitized_name == "alpha"
            assert t2.sanitized_name == "alpha-2"

        asyncio.run(_run())

    def test_delete_nonexistent_raises(self):
        import pytest
        from nuocode.team.manager import Manager
        from nuocode.team.types import TeamNotFoundError

        home = tmp_path()
        root = tmp_path()

        async def _run():
            mgr = Manager(home_dir=home, project_root=root)
            with pytest.raises(TeamNotFoundError):
                await mgr.delete("nonexistent")

        asyncio.run(_run())

    def test_delete_with_active_member_raises(self):
        import pytest
        from nuocode.team.manager import Manager
        from nuocode.team.types import TeamHasActiveMembersError, TeammateInfo, BackendType

        home = tmp_path()
        root = tmp_path()

        async def _run():
            mgr = Manager(home_dir=home, project_root=root)
            team = await mgr.create("myteam")
            m = TeammateInfo(
                name="bob",
                agent_id="agent-bob",
                is_active=True,
                backend_type=BackendType.IN_PROCESS,
            )
            await team.add_member(m)
            with pytest.raises(TeamHasActiveMembersError):
                await mgr.delete("myteam")

        asyncio.run(_run())

    def test_delete_force_with_active(self):
        from nuocode.team.manager import Manager
        from nuocode.team.types import TeammateInfo, BackendType

        home = tmp_path()
        root = tmp_path()

        async def _run():
            mgr = Manager(home_dir=home, project_root=root)
            team = await mgr.create("myteam2")
            m = TeammateInfo(
                name="bob",
                agent_id="agent-bob",
                is_active=True,
                backend_type=BackendType.IN_PROCESS,
            )
            await team.add_member(m)
            await mgr.delete("myteam2", force=True)
            assert mgr.get("myteam2") is None

        asyncio.run(_run())

    def test_get_returns_none_for_unknown(self):
        from nuocode.team.manager import Manager

        home = tmp_path()
        root = tmp_path()
        mgr = Manager(home_dir=home, project_root=root)
        assert mgr.get("does_not_exist") is None

    def test_list_empty(self):
        from nuocode.team.manager import Manager

        home = tmp_path()
        root = tmp_path()
        mgr = Manager(home_dir=home, project_root=root)
        assert mgr.list_() == []


# ── team/mailbox ──────────────────────────────────────────────────────────────

class TestMailboxBox:
    def test_write_and_read(self):
        from nuocode.team.mailbox import Box
        from nuocode.team.mailbox.message import Message, MessageType

        d = tmp_path()

        async def _run():
            box = Box(str(d))
            msg = Message(
                from_="alice",
                to="bob",
                type=MessageType.TEXT,
                summary="hello",
                content="Hello Bob!",
            )
            await box.write("bob", msg)
            indices, messages = await box.read_unread("bob")
            assert len(messages) == 1
            assert messages[0].from_ == "alice"
            assert messages[0].content == "Hello Bob!"
            assert messages[0].read is False
            return indices

        indices = asyncio.run(_run())
        assert len(indices) == 1

    def test_mark_read(self):
        from nuocode.team.mailbox import Box
        from nuocode.team.mailbox.message import Message, MessageType

        d = tmp_path()

        async def _run():
            box = Box(str(d))
            for i in range(3):
                msg = Message(
                    from_="x",
                    to="y",
                    type=MessageType.TEXT,
                    summary=f"msg{i}",
                    content=f"content{i}",
                )
                await box.write("y", msg)

            indices, _ = await box.read_unread("y")
            assert len(indices) == 3
            await box.mark_read("y", indices[:2])

            indices2, messages2 = await box.read_unread("y")
            assert len(messages2) == 1
            assert messages2[0].summary == "msg2"

        asyncio.run(_run())


# ── team/registry ─────────────────────────────────────────────────────────────

class TestAgentNameRegistry:
    def test_register_and_resolve(self):
        from nuocode.team.registry import AgentNameRegistry
        reg = AgentNameRegistry()
        reg.register("alice", "agent-aaa")
        assert reg.resolve("alice") == "agent-aaa"
        assert reg.resolve("agent-aaa") == "agent-aaa"
        assert reg.name_of("agent-aaa") == "alice"

    def test_later_overrides_earlier(self):
        from nuocode.team.registry import AgentNameRegistry
        reg = AgentNameRegistry()
        reg.register("alice", "agent-old")
        reg.register("alice", "agent-new")
        assert reg.resolve("alice") == "agent-new"

    def test_unregister(self):
        from nuocode.team.registry import AgentNameRegistry
        reg = AgentNameRegistry()
        reg.register("alice", "agent-abc")
        reg.unregister("alice")
        assert reg.resolve("alice") is None

    def test_list(self):
        from nuocode.team.registry import AgentNameRegistry
        reg = AgentNameRegistry()
        reg.register("a", "agent-1")
        reg.register("b", "agent-2")
        d = reg.list_()
        assert d["a"] == "agent-1"
        assert d["b"] == "agent-2"


# ── team/tasks ────────────────────────────────────────────────────────────────

class TestTaskStore:
    def test_create_and_get(self):
        from nuocode.team.tasks import Store, Status, Task

        d = tmp_path()
        tasks_path = str(d / "tasks.json")

        async def _run():
            store = Store(tasks_path)
            t = Task(id="", title="Fix bug #123", status=Status.PENDING, created_at=0, updated_at=0)
            task_id = await store.create(t)
            assert task_id.startswith("task_")

            fetched = await store.get(task_id)
            assert fetched.title == "Fix bug #123"

        asyncio.run(_run())

    def test_update_bidirectional(self):
        from nuocode.team.tasks import Store, Patch, Status, Task

        d = tmp_path()
        tasks_path = str(d / "tasks.json")

        async def _run():
            store = Store(tasks_path)
            a = Task(id="", title="A", status=Status.PENDING, created_at=0, updated_at=0)
            b = Task(id="", title="B", status=Status.PENDING, created_at=0, updated_at=0)
            id_a = await store.create(a)
            id_b = await store.create(b)

            # B blocked_by A（双向维护）
            await store.update(id_b, Patch(add_blocked_by=[id_a]))

            fetched_a = await store.get(id_a)
            fetched_b = await store.get(id_b)
            assert id_b in fetched_a.blocks
            assert id_a in fetched_b.blocked_by

        asyncio.run(_run())

    def test_list_is_ready(self):
        from nuocode.team.tasks import Filter, Patch, Status, Store, Task

        d = tmp_path()
        tasks_path = str(d / "tasks.json")

        async def _run():
            store = Store(tasks_path)
            a = Task(id="", title="A", status=Status.PENDING, created_at=0, updated_at=0)
            b = Task(id="", title="B", status=Status.PENDING, created_at=0, updated_at=0)
            id_a = await store.create(a)
            id_b = await store.create(b)
            await store.update(id_b, Patch(add_blocked_by=[id_a]))

            items = await store.list_()
            by_id = {t["id"]: t for t in items}
            # b 的 blocker a 未完成，is_ready=False
            assert by_id[id_b]["is_ready"] is False
            # 完成 a
            await store.update(id_a, Patch(status=Status.COMPLETED))
            items2 = await store.list_()
            by_id2 = {t["id"]: t for t in items2}
            assert by_id2[id_b]["is_ready"] is True

        asyncio.run(_run())


# ── tool/filter.py ────────────────────────────────────────────────────────────

class TestFilterTeammate:
    def test_teammate_true_injects_tools(self):
        from nuocode.tool.filter import FilterParams, TEAMMATE_EXTRA_TOOLS, apply_agent_tool_filter
        all_tools = ["read_file", "write_file", "bash"]
        p = FilterParams(all=all_tools, source=0, background=False, teammate=True)
        result = apply_agent_tool_filter(p)
        for tool in TEAMMATE_EXTRA_TOOLS:
            assert tool in result, f"{tool} 应在结果中"

    def test_teammate_false_excludes_tools(self):
        from nuocode.tool.filter import FilterParams, TEAMMATE_EXTRA_TOOLS, apply_agent_tool_filter
        all_tools = ["read_file", "TaskCreate", "SendMessage"]
        p = FilterParams(all=all_tools, source=0, background=False, teammate=False)
        result = apply_agent_tool_filter(p)
        for tool in TEAMMATE_EXTRA_TOOLS:
            assert tool not in result, f"{tool} 不应在非队员结果中"

    def test_agent_always_excluded(self):
        from nuocode.tool.filter import FilterParams, apply_agent_tool_filter
        p = FilterParams(all=["Agent", "read_file"], source=0, background=False)
        result = apply_agent_tool_filter(p)
        assert "Agent" not in result

    def test_background_teammate_has_extra_tools(self):
        """后台 + 队员模式：同时满足两层过滤但队员工具仍注入。"""
        from nuocode.tool.filter import (
            ASYNC_AGENT_ALLOWED_TOOLS,
            FilterParams,
            TEAMMATE_EXTRA_TOOLS,
            apply_agent_tool_filter,
        )
        all_tools = ASYNC_AGENT_ALLOWED_TOOLS + ["TaskCreate", "SendMessage"]
        p = FilterParams(all=all_tools, source=0, background=True, teammate=True)
        result = apply_agent_tool_filter(p)
        for tool in TEAMMATE_EXTRA_TOOLS:
            assert tool in result


# ── agent/team_hook.py ────────────────────────────────────────────────────────

class TestTeamHook:
    def test_with_teammate_context(self):
        from nuocode.agent.team_hook import (
            TeammateContext,
            WITH_TEAMMATE_KEY,
            teammate_context_from_ctx,
            with_teammate_context,
        )

        async def noop_read():
            return [], []

        async def noop_mark(i):
            pass

        tc = TeammateContext(
            team_name="myteam",
            member_name="alice",
            agent_id="agent-xxx",
            mailbox_dir="/tmp/mailbox",
            read_unread=noop_read,
            mark_read=noop_mark,
        )
        ctx = {}
        ctx2 = with_teammate_context(ctx, tc)
        assert WITH_TEAMMATE_KEY in ctx2

        tc2 = teammate_context_from_ctx(ctx2)
        assert tc2 is not None
        assert tc2.team_name == "myteam"

    def test_none_ctx(self):
        from nuocode.agent.team_hook import teammate_context_from_ctx
        assert teammate_context_from_ctx(None) is None
        assert teammate_context_from_ctx({}) is None

    def test_incoming_message_fields(self):
        from nuocode.agent.team_hook import IncomingMessage
        msg = IncomingMessage(
            from_="lead",
            to="alice",
            type="text",
            summary="hi",
            content="Hello",
        )
        assert msg.from_ == "lead"
        assert msg.type == "text"


# ── coordinator ───────────────────────────────────────────────────────────────

class TestCoordinator:
    def test_disabled_by_default(self):
        from nuocode.coordinator import is_enabled
        cfg = MagicMock()
        cfg.features = MagicMock()
        cfg.features.coordinator_mode = False
        env_backup = os.environ.pop("nuocode_COORDINATOR_MODE", None)
        try:
            result = is_enabled(cfg)
            assert result is False
        finally:
            if env_backup is not None:
                os.environ["nuocode_COORDINATOR_MODE"] = env_backup

    def test_enabled_with_both_flags(self):
        from nuocode.coordinator import is_enabled
        cfg = MagicMock()
        cfg.features = MagicMock()
        cfg.features.coordinator_mode = True
        env_backup = os.environ.get("nuocode_COORDINATOR_MODE")
        os.environ["nuocode_COORDINATOR_MODE"] = "true"
        try:
            assert is_enabled(cfg) is True
        finally:
            if env_backup is None:
                os.environ.pop("nuocode_COORDINATOR_MODE", None)
            else:
                os.environ["nuocode_COORDINATOR_MODE"] = env_backup

    def test_feature_flag_off_env_on(self):
        from nuocode.coordinator import is_enabled
        cfg = MagicMock()
        cfg.features = MagicMock()
        cfg.features.coordinator_mode = False
        env_backup = os.environ.get("nuocode_COORDINATOR_MODE")
        os.environ["nuocode_COORDINATOR_MODE"] = "1"
        try:
            assert is_enabled(cfg) is False
        finally:
            if env_backup is None:
                os.environ.pop("nuocode_COORDINATOR_MODE", None)
            else:
                os.environ["nuocode_COORDINATOR_MODE"] = env_backup

    def test_allowed_tools_list(self):
        from nuocode.coordinator import allowed_tools
        tools = allowed_tools()
        assert "Agent" in tools
        assert "TeamCreate" in tools
        assert "SendMessage" in tools

    def test_system_prompt_suffix(self):
        from nuocode.coordinator import system_prompt_suffix
        suffix = system_prompt_suffix()
        assert "Coordinator Mode" in suffix
        assert "四阶段" in suffix


# ── team/backend/detect.py ────────────────────────────────────────────────────

class TestDetect:
    def test_detect_in_process_fallback(self):
        """无 TMUX 且无 iterm2/tmux 时返回 in-process。"""
        from nuocode.team.backend.detect import detect
        from nuocode.team.types import BackendType

        env_tmux = os.environ.pop("TMUX", None)
        env_term = os.environ.pop("TERM_PROGRAM", None)
        try:
            with patch("shutil.which", return_value=None):
                result = detect()
            assert result == BackendType.IN_PROCESS
        finally:
            if env_tmux is not None:
                os.environ["TMUX"] = env_tmux
            if env_term is not None:
                os.environ["TERM_PROGRAM"] = env_term

    def test_detect_tmux_via_env(self):
        from nuocode.team.backend.detect import detect
        from nuocode.team.types import BackendType

        env_tmux_backup = os.environ.get("TMUX")
        os.environ["TMUX"] = "/tmp/tmux-socket,1234,0"
        try:
            result = detect()
            assert result == BackendType.TMUX
        finally:
            if env_tmux_backup is None:
                os.environ.pop("TMUX", None)
            else:
                os.environ["TMUX"] = env_tmux_backup


# ── team_mailbox.py ───────────────────────────────────────────────────────────

class TestIngestTeamMailbox:
    def test_no_messages_no_op(self):
        from nuocode.agent.team_mailbox import ingest_team_mailbox
        from nuocode.agent.team_hook import TeammateContext

        async def noop_read():
            return [], []

        async def noop_mark(i):
            pass

        tc = TeammateContext(
            team_name="t",
            member_name="m",
            agent_id="aid",
            mailbox_dir="/tmp",
            read_unread=noop_read,
            mark_read=noop_mark,
        )
        runtime = MagicMock()
        runtime.pending_reminders = []

        asyncio.run(ingest_team_mailbox(tc, runtime, None))
        assert runtime.pending_reminders == []

    def test_messages_appended_as_reminder(self):
        from nuocode.agent.team_mailbox import ingest_team_mailbox
        from nuocode.agent.team_hook import IncomingMessage, TeammateContext

        msgs = [
            IncomingMessage(
                from_="lead",
                to="alice",
                type="text",
                summary="test summary",
                content="Hello there",
                timestamp=0,
            )
        ]

        async def read_msgs():
            return [0], msgs

        async def noop_mark(i):
            pass

        tc = TeammateContext(
            team_name="t",
            member_name="m",
            agent_id="aid",
            mailbox_dir="/tmp",
            read_unread=read_msgs,
            mark_read=noop_mark,
        )

        # 使用有 pending_reminders 的真实 runtime mock
        class _FakeRuntime:
            def __init__(self):
                self.pending_reminders: list[str] = []

        runtime = _FakeRuntime()

        asyncio.run(ingest_team_mailbox(tc, runtime, None))
        assert len(runtime.pending_reminders) == 1
        assert "incoming-messages" in runtime.pending_reminders[0]
