"""tool ctx：with_cwd / cwd_from_ctx / resolve_path（chap14 F16）。

通过 ``contextvars.ContextVar`` 在异步上下文中传递 explicit cwd，
避免修改进程级 ``os.chdir``，防止并发组件之间的同步点。

用法：
    with with_cwd("/path/to/worktree"):
        # 此 context 中所有工具调用 resolve_path 都以 /path/to/worktree 为基准
        result = await some_tool.execute(args)
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_ctx_cwd: ContextVar[str | None] = ContextVar("cwd", default=None)


@contextmanager
def with_cwd(directory: str) -> Generator[None, None, None]:
    """设置当前 async context 的工作目录。

    空字符串时不改变 ctx，直接 yield。
    """
    if not directory:
        yield
        return
    token = _ctx_cwd.set(directory)
    try:
        yield
    finally:
        _ctx_cwd.reset(token)


def cwd_from_ctx() -> str | None:
    """获取当前 async context 中设置的 cwd。未设置返回 None。"""
    return _ctx_cwd.get()


def resolve_path(p: str) -> str:
    """解析路径为绝对路径。

    规则：
    - ``p`` 为空：返回 ctx cwd 或进程 cwd
    - ``p`` 是绝对路径：直接返回
    - 否则：以 ctx cwd（优先）或进程 cwd 为基准拼接
    """
    base = _ctx_cwd.get() or str(Path.cwd())
    if not p:
        return base
    pp = Path(p)
    if pp.is_absolute():
        return str(pp)
    return str(Path(base) / p)
