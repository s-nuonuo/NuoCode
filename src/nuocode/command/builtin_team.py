"""Team 相关 slash 命令（chap15 T27 F59-F62）。

提供 /team <subcommand> 命令族，注册到 Registry。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nuocode.command.registry import Registry
    from nuocode.command.ui import UI
    from nuocode.team.manager import Manager


def make_team_handler(team_mgr: Manager):
    """创建 /team 命令 handler（闭包绑定 team_mgr）。"""

    async def handle_team(ui: UI, args: str) -> None:
        parts = args.strip().split()
        if not parts:
            ui.println(
                "用法：/team <subcommand>\n"
                "  /team list           列出所有 Team\n"
                "  /team info <name>    展示 Team 详情\n"
                "  /team delete <name> [--force]  删除 Team\n"
                "  /team kill <member>  终止并移除队员"
            )
            return

        sub_cmd = parts[0]
        rest = parts[1:]

        if sub_cmd == "list":
            await _team_list(ui, team_mgr)
        elif sub_cmd == "info":
            if not rest:
                ui.error("/team info: 缺少 <name>")
                return
            await _team_info(ui, team_mgr, rest[0])
        elif sub_cmd == "delete":
            if not rest:
                ui.error("/team delete: 缺少 <name>")
                return
            force = "--force" in rest
            await _team_delete(ui, team_mgr, rest[0], force)
        elif sub_cmd == "kill":
            if not rest:
                ui.error("/team kill: 缺少 <member>")
                return
            await _team_kill(ui, team_mgr, rest[0])
        else:
            ui.error(f"/team: 未知子命令 {sub_cmd!r}（支持 list/info/delete/kill）")

    return handle_team


async def _team_list(ui: UI, team_mgr: Manager) -> None:
    """列出所有 Team（F59）。"""
    teams = team_mgr.list_()
    if not teams:
        ui.println("当前没有 Team。使用 TeamCreate 工具创建。")
        return
    ui.println("Team 列表：")
    for t in teams:
        active = sum(
            1 for m in t.members if m.is_active is not False and m.name != "lead"
        )
        total = len([m for m in t.members if m.name != "lead"])
        ui.println(
            f"  {t.sanitized_name}  [{str(t.backend)}]  "
            f"{total} 成员  [{active}/{total}] 活跃"
        )


async def _team_info(ui: UI, team_mgr: Manager, name: str) -> None:
    """展示 Team 详情（F60）。"""
    team = team_mgr.get(name)
    if team is None:
        ui.error(f"Team {name!r} 不存在")
        return
    ui.println(f"Team: {team.name}（sanitized: {team.sanitized_name}）")
    ui.println(f"  后端: {team.backend}")
    ui.println(f"  配置路径: {team.config_path}")
    ui.println("  成员列表:")
    for m in team.members:
        active_str = "活跃" if m.is_active is not False else "空闲"
        ui.println(
            f"    {m.name}  [{active_str}]  "
            f"agent_id={m.agent_id}  "
            f"backend={m.backend_type}  "
            f"pane={m.pane_id or '-'}"
        )
        if m.worktree_path:
            ui.println(f"      worktree: {m.worktree_path}")


async def _team_delete(ui: UI, team_mgr: Manager, name: str, force: bool) -> None:
    """删除 Team（F61）。"""
    from nuocode.team.types import TeamHasActiveMembersError, TeamNotFoundError

    try:
        await team_mgr.delete(name, force=force)
        ui.println(f"Team {name!r} 已删除")
    except TeamNotFoundError:
        ui.error(f"Team {name!r} 不存在")
    except TeamHasActiveMembersError as e:
        ui.error(
            f"删除失败：{e}\n"
            f"提示：使用 /team delete {name} --force 强制删除"
        )
    except Exception as e:  # noqa: BLE001
        ui.error(f"删除失败：{e}")


async def _team_kill(ui: UI, team_mgr: Manager, member_name: str) -> None:
    """杀死指定队员（F62）。"""
    for team in team_mgr.list_():
        member = team.member_by_name(member_name)
        if member is not None:
            try:
                from nuocode.team.backend import new_backend
                backend = new_backend(member.backend_type, task_mgr=team_mgr.task_mgr)
                await backend.kill(member.pane_id, member.agent_id)
            except Exception as e:  # noqa: BLE001
                ui.error(f"kill 失败：{e}")
                return
            try:
                await team.remove_member(member_name)
            except Exception as e:  # noqa: BLE001
                ui.error(f"kill 成功，但 remove_member 失败：{e}")
                return
            ui.println(f"队员 {member_name!r} 已终止并从 Team {team.sanitized_name!r} 移除")
            return

    ui.error(f"找不到队员 {member_name!r}")


def register_team_commands(registry: Registry, team_mgr: Manager) -> None:
    """注册 /team 命令到 Registry。"""
    from nuocode.command.command import Command, Kind

    handler = make_team_handler(team_mgr)
    registry.register(
        Command(
            name="team",
            description="管理 Agent Team（list/info/delete/kill）",
            kind=Kind.LOCAL,
            handler=handler,
        )
    )
