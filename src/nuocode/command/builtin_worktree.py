"""builtin_worktree.py：/worktree 命令 handler（chap14 F24-F29/T13）。

支持子命令：create / list / enter / exit / remove
输出走 ui.println / ui.error，不进对话历史。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nuocode.command.ui import UI


async def handle_worktree(ui: UI, args: str) -> None:
    """处理 /worktree 命令。args 是 /worktree 后面的全部尾随字符串。"""
    parts = args.strip().split()
    if not parts:
        _usage(ui)
        return

    sub_cmd = parts[0]
    rest = parts[1:]

    accessor = ui.worktree_accessor()

    if sub_cmd == "create":
        if not rest:
            ui.error("/worktree create: 缺少 <slug>")
            return
        if accessor is None:
            ui.error("Worktree 管理器未启用（非 git 仓库或初始化失败）")
            return
        slug = rest[0]
        try:
            path, branch = await accessor.create(slug)
            ui.println(f"Worktree 已创建: {path} (分支 {branch})")
        except Exception as e:  # noqa: BLE001
            ui.error(f"创建失败: {e}")

    elif sub_cmd == "list":
        if accessor is None:
            ui.error("Worktree 管理器未启用（非 git 仓库或初始化失败）")
            return
        items = accessor.list()
        if not items:
            ui.println("（无 Worktree）")
            return
        # 取当前活跃 session（通过 accessor 暂无该接口，直接标注 active 字段）
        for wt in items:
            active_mark = "[active]" if wt.active else ""
            manual_mark = "[manual]" if wt.manual else "[auto]"
            ui.println(f"  {wt.name:20s}  {wt.path}  {wt.branch}  {active_mark} {manual_mark}")

    elif sub_cmd == "enter":
        if not rest:
            ui.error("/worktree enter: 缺少 <slug>")
            return
        if accessor is None:
            ui.error("Worktree 管理器未启用（非 git 仓库或初始化失败）")
            return
        slug = rest[0]
        try:
            await accessor.enter(slug)
            ui.println(f"已进入 Worktree: {slug}")
        except Exception as e:  # noqa: BLE001
            ui.error(f"进入失败: {e}")

    elif sub_cmd == "exit":
        if accessor is None:
            ui.error("Worktree 管理器未启用（非 git 仓库或初始化失败）")
            return
        do_remove = "--remove" in rest
        discard = "--discard" in rest
        action = "remove" if do_remove else "keep"
        try:
            removed = await accessor.exit(action, discard)
            if removed:
                ui.println("已退出并删除 Worktree")
            else:
                ui.println("已退出 Worktree（保留目录）")
        except Exception as e:  # noqa: BLE001
            ui.error(f"退出失败: {e}")

    elif sub_cmd == "remove":
        if not rest or rest[0].startswith("--"):
            ui.error("/worktree remove: 缺少 <slug>")
            return
        if accessor is None:
            ui.error("Worktree 管理器未启用（非 git 仓库或初始化失败）")
            return
        slug = rest[0]
        discard = "--discard" in rest
        try:
            await accessor.remove(slug, discard)
            ui.println(f"Worktree {slug!r} 已删除")
        except Exception as e:  # noqa: BLE001
            ui.error(f"删除失败: {e}")

    else:
        ui.error(f"未知 /worktree 子命令: {sub_cmd!r}")
        _usage(ui)


def _usage(ui: UI) -> None:
    ui.println(
        "用法:\n"
        "  /worktree create <slug>          — 创建 Worktree\n"
        "  /worktree list                   — 列出所有 Worktree\n"
        "  /worktree enter <slug>           — 进入 Worktree\n"
        "  /worktree exit [--remove] [--discard]  — 退出当前 Worktree\n"
        "  /worktree remove <slug> [--discard]    — 删除 Worktree"
    )
