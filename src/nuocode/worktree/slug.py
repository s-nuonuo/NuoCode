"""Worktree slug 校验与扁平化（chap14 F1-F2）。

- ``validate_slug``: 校验 slug 合法性，失败抛 ValueError
- ``flat_slug``: 将 slug 中的 ``/`` 替换为 ``+``，用于文件系统路径与 Git 分支名
"""

from __future__ import annotations

import re

_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
_MAX_LEN = 64


def validate_slug(name: str) -> None:
    """校验 worktree slug 合法性。

    规则：
    - name 非空
    - 总长度 ≤ 64
    - 按 ``/`` 切段，每段必须匹配 ``^[a-zA-Z0-9._-]+$`` 且不能是 ``.`` 或``..``
    - 不允许连续 ``//``、首末 ``/``

    失败时抛 ``ValueError`` 携带具体原因。
    """
    if not name:
        raise ValueError("slug 不能为空")
    if len(name) > _MAX_LEN:
        raise ValueError(f"slug 长度超过上限 {_MAX_LEN}，当前 {len(name)}")
    if "//" in name:
        raise ValueError("slug 不允许连续 '//'")
    if name.startswith("/"):
        raise ValueError("slug 不允许以 '/' 开头")
    if name.endswith("/"):
        raise ValueError("slug 不允许以 '/' 结尾")
    segments = name.split("/")
    for seg in segments:
        if seg == "." or seg == "..":
            raise ValueError(f"slug 段名不允许是 '.' 或 '..'，非法段：{seg!r}")
        if not _SEGMENT_RE.match(seg):
            raise ValueError(
                f"slug 段名只允许字母、数字、'.'、'_'、'-'，非法段：{seg!r}"
            )


def flat_slug(name: str) -> str:
    """将 slug 中的 ``/`` 替换为 ``+``，用于文件系统路径与 Git 分支名。

    示例：``team/alice`` → ``team+alice``
    """
    return name.replace("/", "+")
