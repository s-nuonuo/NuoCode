"""把 importlib.resources 中的内置 Skill 资源 materialize 到 cache 目录。"""

from __future__ import annotations

import os
import shutil
from importlib.resources import as_file, files
from pathlib import Path


def _cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".cache"
    return root / "nuocode" / "builtin-skills"


def materialize_builtin_skills() -> list[Path]:
    """把所有内置 Skill 目录复制到 cache 路径，返回每个 Skill 的 cache 目录列表。"""
    out: list[Path] = []
    root = _cache_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        base = files("nuocode.skills.builtin")
    except (ModuleNotFoundError, FileNotFoundError):
        return out

    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        if not entry.joinpath("SKILL.md").is_file():
            continue
        name = entry.name
        target = root / name
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        for sub in entry.iterdir():
            if sub.is_file():
                with as_file(sub) as real:
                    shutil.copy(real, target / sub.name)
            elif sub.is_dir():
                with as_file(sub) as real:
                    shutil.copytree(real, target / sub.name)
        out.append(target)
    return out


__all__ = ["materialize_builtin_skills"]
