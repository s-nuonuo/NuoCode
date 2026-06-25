"""WorktreeSession 数据结构与 JSON 原子持久化（chap14 F3/F30-F32）。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class WorktreeSession:
    """当前活跃的 Worktree 会话信息。

    字段：
    - ``original_cwd``: 进入 Worktree 前的工作目录
    - ``worktree_path``: Worktree 绝对路径
    - ``worktree_name``: 原始 slug（可能含 /）
    - ``original_branch``: 进入前的 Git 分支名
    - ``original_head_commit``: 进入前的 HEAD commit SHA
    - ``session_id``: UUID 字符串，保证唯一
    - ``hook_based``: 预留字段
    """

    original_cwd: str
    worktree_path: str
    worktree_name: str
    original_branch: str
    original_head_commit: str
    session_id: str
    hook_based: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> WorktreeSession:
        return cls(**json.loads(raw))


def load_session(path: Path) -> WorktreeSession | None:
    """从文件加载 WorktreeSession。

    - 文件不存在：返回 None
    - 文件内容为 ``null`` 或空：返回 None
    - JSON 解析失败：抛出 ValueError
    """
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text or text == "null":
        return None
    try:
        return WorktreeSession.from_json(text)
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        raise ValueError(f"worktree_session.json 解析失败: {e}") from e


def save_session(path: Path, session: WorktreeSession | None) -> None:
    """原子写 WorktreeSession 到文件。

    session=None 时写入 ``null``；使用 tmp 文件 + os.replace 原子替换。
    """
    content = session.to_json() if session is not None else "null"
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


def clear_session(path: Path) -> None:
    """清空 session 文件（写入 null）。等同于 save_session(path, None)。"""
    save_session(path, None)
