"""命令注册中心：注册 + 冲突检测 + lookup + 字典序 visible + 前缀匹配。"""

from __future__ import annotations

from nuocode.command.command import Command


class Registry:
    def __init__(self) -> None:
        self._by_name: dict[str, Command] = {}
        self._visible: list[Command] = []

    def register(self, cmd: Command) -> None:
        if not cmd.name or cmd.name != cmd.name.lower() or " " in cmd.name:
            raise RuntimeError(f"invalid command name: {cmd.name!r}")
        for a in cmd.aliases:
            if not a or a != a.lower() or " " in a:
                raise RuntimeError(f"invalid command alias: {a!r}")
        for key in (cmd.name, *cmd.aliases):
            if key in self._by_name:
                raise RuntimeError(f"command conflict: {key!r}")
        for key in (cmd.name, *cmd.aliases):
            self._by_name[key] = cmd
        if not cmd.hidden:
            self._visible.append(cmd)
            self._visible.sort(key=lambda c: c.name)

    def lookup(self, name: str) -> Command | None:
        if not name:
            return None
        return self._by_name.get(name.lower())

    def visible(self) -> list[Command]:
        return list(self._visible)

    def prefix_match(self, prefix: str) -> list[Command]:
        p = prefix.lstrip("/").lower()
        if p == "":
            return list(self._visible)
        return [c for c in self._visible if c.name.startswith(p)]


__all__ = ["Registry"]
