"""Catalog: 三层路径扫描（builtin / user / project）+ 覆盖优先级 + 工具校验。"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from nuocode.skills.embed_builtin import materialize_builtin_skills
from nuocode.skills.parser import parse_skill_dir
from nuocode.skills.types import Skill, SkillSource


@dataclass
class ValidationIssue:
    skill_name: str
    tool_name: str


# 内置命令名（用于冲突保护，与 ch10 register_builtins 保持一致；删除 review 后允许同名 Skill）
_RESERVED_COMMAND_NAMES = {
    "clear",
    "compact",
    "do",
    "exit",
    "help",
    "memory",
    "permission",
    "plan",
    "resume",
    "session",
    "status",
    "skill",
}

# 系统工具：fail-fast 校验时视为可用
_SYSTEM_TOOL_NAMES = {"load_skill", "install_skill"}


class Catalog:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_name: dict[str, Skill] = {}
        self._order: list[str] = []

    def register(self, s: Skill) -> None:
        with self._lock:
            if s.meta.name in self._by_name:
                self._by_name[s.meta.name] = s
                return
            self._by_name[s.meta.name] = s
            self._order.append(s.meta.name)
            self._order.sort()

    def remove(self, name: str) -> None:
        with self._lock:
            if name in self._by_name:
                del self._by_name[name]
            if name in self._order:
                self._order.remove(name)

    def get(self, name: str) -> Skill | None:
        with self._lock:
            return self._by_name.get(name)

    def list(self) -> list[Skill]:
        with self._lock:
            return [self._by_name[n] for n in self._order]

    def names(self) -> list[str]:
        with self._lock:
            return list(self._order)

    @classmethod
    def load(cls, work_dir: Path) -> Catalog:
        c = cls()
        _load_builtin_into(c)
        _load_dir_into(c, Path.home() / ".nuocode" / "skills", SkillSource.USER)
        _load_dir_into(c, Path(work_dir) / ".nuocode" / "skills", SkillSource.PROJECT)
        return c

    def reload(self, work_dir: Path) -> None:
        new = Catalog.load(work_dir)
        with self._lock:
            self._by_name = dict(new._by_name)
            self._order = list(new._order)

    def validate_tools(self, registry) -> list[ValidationIssue]:  # noqa: ANN001
        issues: list[ValidationIssue] = []
        for s in self.list():
            for tool in s.meta.allowed_tools:
                if tool in _SYSTEM_TOOL_NAMES:
                    continue
                if registry.get(tool) is None:
                    issues.append(ValidationIssue(skill_name=s.meta.name, tool_name=tool))
        return issues


def _load_builtin_into(c: Catalog) -> None:
    try:
        cache_dirs = materialize_builtin_skills()
    except Exception as e:  # noqa: BLE001
        print(f"[skills] warn: materialize builtin skills failed: {e}", file=sys.stderr)
        return
    for d in cache_dirs:
        try:
            sk = parse_skill_dir(d, SkillSource.BUILTIN)
        except Exception as e:  # noqa: BLE001
            print(f"[skills] warn: parse builtin {d.name} failed: {e}", file=sys.stderr)
            continue
        c.register(sk)


def _load_dir_into(c: Catalog, base_dir: Path, source: SkillSource) -> None:
    if not base_dir.is_dir():
        return
    for entry in sorted(base_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "SKILL.md").is_file():
            print(f"[skills] warn: {entry} has no SKILL.md, skipped", file=sys.stderr)
            continue
        try:
            sk = parse_skill_dir(entry, source)
        except Exception as e:  # noqa: BLE001
            print(f"[skills] warn: parse {entry} failed: {e}", file=sys.stderr)
            continue
        if sk.meta.name in _RESERVED_COMMAND_NAMES:
            print(
                f"[skills] warn: skill {sk.meta.name!r} conflicts with builtin command, skipped",
                file=sys.stderr,
            )
            continue
        c.register(sk)


__all__ = ["Catalog", "ValidationIssue"]
