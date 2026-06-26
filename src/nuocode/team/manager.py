"""Team Manager（chap15 F3-F10、F66）。

Manager 在单 nuocode 进程内管理多个 Team，典型场景同时只有一个活跃 Team。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nuocode.team.persistence import (
    atomic_write_json,
    read_json,
    reload_from_disk_locked,
    sanitize,
)
from nuocode.team.types import (
    BackendType,
    MemberExistsError,
    MemberNotFoundError,
    Team,
    TeamHasActiveMembersError,
    TeammateInfo,
    TeamNotFoundError,
)

if TYPE_CHECKING:
    import asyncio

    from nuocode.task.manager import Manager as TaskManager
    from nuocode.team.registry import AgentNameRegistry
    from nuocode.worktree.manager import Manager as WorktreeManager


class Manager:
    """Team 管理器（F3-F4）。

    属性：
    - _lock: asyncio.Lock，保护 teams dict
    - teams: dict[str, Team]，按 sanitized_name 索引
    - home_dir: Path.home()
    - wt_mgr: worktree.Manager
    - task_mgr: task.Manager
    - registry: AgentNameRegistry
    """

    def __init__(
        self,
        home_dir: str | Path,
        project_root: str | Path,
        wt_mgr: WorktreeManager | None = None,
        task_mgr: TaskManager | None = None,
        registry: AgentNameRegistry | None = None,
    ) -> None:
        import asyncio

        self.home_dir = Path(home_dir)
        self.project_root = Path(project_root)
        self.wt_mgr = wt_mgr
        self.task_mgr = task_mgr
        self.registry = registry
        self._lock: asyncio.Lock = asyncio.Lock()
        self.teams: dict[str, Team] = {}

        # 确保 teams 目录存在
        teams_dir = self._teams_dir()
        teams_dir.mkdir(parents=True, exist_ok=True)

        # 扫描已有 Team 目录（F4）
        self._scan_teams(teams_dir)

        # chap15 T21：注册 on_task_done 回调
        if task_mgr is not None:
            task_mgr.on_task_done(self.handle_task_done)

    def _teams_dir(self) -> Path:
        return self.home_dir / ".nuocode" / "teams"

    def _scan_teams(self, teams_dir: Path) -> None:
        """扫描 teams 目录，还原 teams dict（F4）。"""
        for child in teams_dir.iterdir():
            if not child.is_dir():
                continue
            config_path = child / "config.json"
            if not config_path.exists():
                continue
            try:
                data = read_json(config_path)
                team = Team.from_dict(data, str(child))
                self.teams[team.sanitized_name] = team
            except Exception as e:  # noqa: BLE001
                print(
                    f"[team] 跳过损坏的 Team 目录 {child}: {e}",
                    file=sys.stderr,
                )

    # ── 查询 ──────────────────────────────────────────────────────────────────

    def get(self, name: str) -> Team | None:
        """按 sanitized name 查询 Team（F6）。"""
        sname = sanitize(name)
        return self.teams.get(sname) or self.teams.get(name)

    def list_(self) -> list[Team]:
        """列出所有 Team，按创建时间排序（F3）。"""
        return sorted(self.teams.values(), key=lambda t: t.created_at)

    # ── 创建 ──────────────────────────────────────────────────────────────────

    async def create(self, name: str, description: str = "") -> Team:
        """创建新 Team（F5）。

        1. sanitize name
        2. 同名冲突时追加 -2/-3 后缀
        3. 创建 config_dir、mailbox_dir
        4. 调 detect_backend()
        5. Lead 注册为第一个成员
        6. atomic_write_json config.json
        7. 加入 teams dict
        """
        from nuocode.team.backend.detect import detect

        async with self._lock:
            sname = sanitize(name)
            if not sname:
                raise ValueError(f"非法 Team 名: {name!r}（sanitize 后为空）")

            # 同名冲突处理
            final_sname = sname
            suffix = 2
            while final_sname in self.teams:
                final_sname = f"{sname}-{suffix}"
                suffix += 1

            config_dir = self._teams_dir() / final_sname
            config_dir.mkdir(parents=True, exist_ok=True)

            mailbox_dir = config_dir / "mailbox"
            mailbox_dir.mkdir(parents=True, exist_ok=True)

            # 检测后端
            backend = detect()

            # 构造 Lead 成员
            lead_info = TeammateInfo(
                name="lead",
                agent_id="lead",
                is_active=None,
                backend_type=backend,
            )

            from datetime import datetime

            team = Team(
                name=name,
                sanitized_name=final_sname,
                lead_agent_id="lead",
                backend=backend,
                description=description,
                created_at=datetime.now(),
                members=[lead_info],
                config_dir=str(config_dir),
            )
            team.config_path = str(config_dir / "config.json")
            team.tasks_path = str(config_dir / "tasks.json")
            team.mailbox_dir = str(mailbox_dir)

            # 原子写 config.json
            atomic_write_json(team.config_path, team.to_dict())

            self.teams[final_sname] = team
            return team

    # ── 删除 ──────────────────────────────────────────────────────────────────

    async def delete(self, name: str, force: bool = False) -> None:
        """删除 Team（F7、F66）。

        顺序：持锁 → 校验 force → kill pane → 清资源 → 删目录 → 移除 dict
        """
        async with self._lock:
            team = self.get(name)
            if team is None:
                raise TeamNotFoundError(f"Team 不存在: {name!r}")

            # 非 force 时校验无活跃成员
            if not force:
                active = [
                    m for m in team.members
                    if m.is_active is not False and m.name != "lead"
                ]
                if active:
                    names = [m.name for m in active]
                    raise TeamHasActiveMembersError(
                        f"Team {name!r} 有活跃成员 {names}，使用 force=True 强制删除"
                    )

            # kill 每个非 lead 成员的 pane/task
            for member in list(team.members):
                if member.name == "lead":
                    continue
                try:
                    backend = _get_backend(member.backend_type, self.task_mgr)
                    if backend is not None:
                        await backend.kill(member.pane_id, member.agent_id)
                except Exception as e:  # noqa: BLE001
                    print(
                        f"[team] kill 成员 {member.name} 失败（继续）: {e}",
                        file=sys.stderr,
                    )

                # 清理 session 目录
                await self._cleanup_member_resources(member)

            # 删整个 Team 目录
            try:
                shutil.rmtree(team.config_dir, ignore_errors=True)
            except Exception as e:  # noqa: BLE001
                print(f"[team] 删 Team 目录失败: {e}", file=sys.stderr)

            # 从 in-memory dict 移除
            self.teams.pop(team.sanitized_name, None)

    async def _cleanup_member_resources(self, member: TeammateInfo) -> None:
        """清理队员的 session 目录与 worktree（best-effort）。"""
        # 删 session 目录
        if member.session_dir:
            try:
                shutil.rmtree(member.session_dir, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass

        # 删 worktree
        if self.wt_mgr is not None and member.worktree_path:
            try:
                # 从 worktree_path 推算 slug
                wt_path = Path(member.worktree_path)
                # worktree slug 是 team-<team>+<member> 格式
                # 这里直接通过 worktree_mgr 按路径删除
                await self._remove_worktree_by_path(str(wt_path))
            except Exception as e:  # noqa: BLE001
                print(
                    f"[team] 删 worktree {member.worktree_path} 失败（继续）: {e}",
                    file=sys.stderr,
                )

    async def _remove_worktree_by_path(self, wt_path: str) -> None:
        """通过路径删除 worktree。"""
        if self.wt_mgr is None:
            return
        # 遍历 worktree_mgr 找到对应 slug
        try:
            sessions = self.wt_mgr._sessions  # type: ignore[attr-defined]
            for slug, session in list(sessions.items()):
                if hasattr(session, "worktree_path") and str(session.worktree_path) == wt_path:
                    await self.wt_mgr.remove(slug, discard_changes=True)
                    return
        except Exception:  # noqa: BLE001
            pass

    # ── handle_task_done ─────────────────────────────────────────────────────

    async def handle_task_done(self, agent_id: str) -> None:
        """队员任务完成回调（T30）。

        1. 通过 registry 反查 name
        2. 找到所属 Team
        3. set_member_active(name, False)
        4. 给 Lead 邮箱写 idle 消息
        """
        from nuocode.team.mailbox import Box
        from nuocode.team.mailbox.message import Message, MessageType

        # 查 name
        member_name: str | None = None
        if self.registry is not None:
            member_name = self.registry.name_of(agent_id)

        # 找所属 Team 和成员
        target_team: Team | None = None
        target_member: TeammateInfo | None = None
        for team in self.teams.values():
            m = team.member_by_agent_id(agent_id)
            if m is not None:
                target_team = team
                target_member = m
                member_name = member_name or m.name
                break

        if target_team is None or target_member is None:
            return

        # 设为 idle
        try:
            await target_team.set_member_active(member_name, False)
        except Exception as e:  # noqa: BLE001
            print(f"[team] set_member_active 失败: {e}", file=sys.stderr)

        # 给 Lead 邮箱写 idle 消息
        try:
            box = Box(target_team.mailbox_dir)
            import time

            msg = Message(
                from_=member_name or agent_id,
                to=target_team.lead_agent_id,
                type=MessageType.TEXT,
                summary=f"{member_name} idle",
                content=f"agent {agent_id} finished work, available for new tasks",
                timestamp=int(time.time()),
            )
            await box.write(target_team.lead_agent_id, msg)
        except Exception as e:  # noqa: BLE001
            print(f"[team] 写 Lead idle 通知失败: {e}", file=sys.stderr)

    # ── poll_lead_mailboxes ───────────────────────────────────────────────────

    async def poll_lead_mailboxes(self) -> list[Any]:
        """轮询所有 Team 的 Lead mailbox，返回 LeadMessage 列表（T30b）。"""
        from nuocode.team.mailbox import Box

        results: list[Any] = []
        for team in self.teams.values():
            try:
                box = Box(team.mailbox_dir)
                indices, messages = await box.read_unread(team.lead_agent_id)
                if messages:
                    await box.mark_read(team.lead_agent_id, indices)
                    for msg in messages:
                        results.append(
                            LeadMessage(
                                team_name=team.sanitized_name,
                                from_=msg.from_,
                                type=str(msg.type),
                                summary=msg.summary,
                                content=msg.content[:8000],
                                timestamp=msg.timestamp,
                            )
                        )
            except Exception as e:  # noqa: BLE001
                print(f"[team] poll_lead_mailboxes 失败: {e}", file=sys.stderr)
        return results


class LeadMessage:
    """Lead 侧收到的消息（T30b）。"""

    def __init__(
        self,
        team_name: str,
        from_: str,
        type: str,
        summary: str,
        content: str,
        timestamp: int,
    ) -> None:
        self.team_name = team_name
        self.from_ = from_
        self.type = type
        self.summary = summary
        self.content = content
        self.timestamp = timestamp


# ── Team 成员操作方法（T4）────────────────────────────────────────────────────
# 把方法注入到 Team dataclass（避免循环导入，统一在 manager.py 定义）

async def _team_add_member(self: Team, info: TeammateInfo) -> None:
    """向 Team 添加成员（F8）。"""
    async with self._lock:
        await reload_from_disk_locked(self)
        if self.member_by_name(info.name) is not None:
            raise MemberExistsError(f"队员名 {info.name!r} 已存在于 Team {self.name!r}")
        self.members.append(info)
        atomic_write_json(self.config_path, self.to_dict())


async def _team_set_member_active(self: Team, name: str, active: bool) -> None:
    """设置队员活跃状态（F9）。"""
    async with self._lock:
        await reload_from_disk_locked(self)
        member = self.member_by_name(name)
        if member is None:
            return  # 静默返回，避免跨进程时序问题
        member.is_active = active
        atomic_write_json(self.config_path, self.to_dict())


async def _team_remove_member(self: Team, name: str) -> None:
    """从 Team 移除成员（F10）。"""
    async with self._lock:
        await reload_from_disk_locked(self)
        before = len(self.members)
        self.members = [m for m in self.members if m.name != name]
        if len(self.members) == before:
            raise MemberNotFoundError(f"队员 {name!r} 不存在于 Team {self.name!r}")
        atomic_write_json(self.config_path, self.to_dict())


# 动态注入到 Team 类
Team.add_member = _team_add_member  # type: ignore[attr-defined]
Team.set_member_active = _team_set_member_active  # type: ignore[attr-defined]
Team.remove_member = _team_remove_member  # type: ignore[attr-defined]


def _get_backend(backend_type: BackendType | str, task_mgr: Any) -> Any | None:
    """按 backend_type 获取 Backend 实例（简单工厂）。"""
    try:
        from nuocode.team.backend import new_backend
        return new_backend(backend_type, task_mgr=task_mgr)
    except Exception:  # noqa: BLE001
        return None
