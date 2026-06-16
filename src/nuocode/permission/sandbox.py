"""路径沙箱（N2）：先解析符号链接、再做前缀比对；不存在的目标回退到最近已存在祖先。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nuocode.permission.engine import Engine


def resolve_root(root: str) -> str:
    """解析项目根（必须存在；展开 ~ 与符号链接）。"""
    return str(Path(root).expanduser().resolve(strict=True))


def eval_symlinks_or_ancestor(abs_path: str) -> str:
    """对存在目标 resolve；不存在则取最近已存在祖先 resolve 后拼回剩余段。"""
    p = Path(abs_path)
    if p.exists() or p.is_symlink():
        try:
            return str(p.resolve(strict=True))
        except (OSError, FileNotFoundError):
            pass
    # 逐级向上找已存在祖先
    parts = list(p.parts)
    if not parts:
        return abs_path
    cur = Path(parts[0])
    last_exist_idx = -1
    for i in range(1, len(parts) + 1):
        cand = Path(*parts[:i])
        if cand.exists():
            cur = cand
            last_exist_idx = i - 1
        else:
            break
    if last_exist_idx < 0:
        # 连根都不存在（异常情况），返回规整后的绝对路径
        return str(p)
    try:
        resolved_anc = Path(*parts[: last_exist_idx + 1]).resolve(strict=True)
    except (OSError, FileNotFoundError):
        resolved_anc = cur
    rest = parts[last_exist_idx + 1 :]
    if rest:
        return str(resolved_anc.joinpath(*rest))
    return str(resolved_anc)


def sandbox_ok(engine: Engine, path: str) -> bool:
    """空 path 视为 root；相对路径相对 root 解析；返回是否落在 root 子树内。"""
    root = engine.root
    if not path:
        return True
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path(root) / p
    resolved = eval_symlinks_or_ancestor(str(p))
    if resolved == root:
        return True
    return resolved.startswith(root + os.sep)


__all__ = ["eval_symlinks_or_ancestor", "resolve_root", "sandbox_ok"]
