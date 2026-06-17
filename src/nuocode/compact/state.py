"""compact 包的会话级状态对象。

包含：
- SessionContext：会话生命周期信息（session_id + session_dir + spill_dir）
- ContentReplacementState：工具结果替换决策账本（决策冻结）
- AutoCompactTrackingState：自动摘要熔断计数
- FileReadRecord / RecoveryState：最近读过的文件追踪状态
"""

from __future__ import annotations

import copy
import logging
import os
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nuocode.compact.const import MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES

logger = logging.getLogger(__name__)


# ───────── 会话上下文 ─────────


@dataclass
class SessionContext:
    """会话生命周期信息。

    - ``session_id``：进程启动时一次生成，形如 ``YYYYMMDD-HHMMSS-xxxx``。
    - ``session_dir``：会话目录绝对路径，``<workspace>/.nuocode/sessions/<session_id>``。
    - ``spill_dir``：工具结果落盘目录，``<session_dir>/tool-results``。
    """

    session_id: str
    session_dir: str
    spill_dir: str


def _new_session_id() -> str:
    """生成会话 id：``YYYYMMDD-HHMMSS-xxxx``（4 字符 hex）。"""
    try:
        hex_str = secrets.token_hex(2)
    except Exception:  # noqa: BLE001
        import random
        import time

        logger.warning("secrets.token_hex 失败，降级到 random.Random")
        hex_str = random.Random(time.time()).randbytes(2).hex()
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{hex_str}"


def new_session_context(workspace: str) -> SessionContext:
    """创建一个新会话上下文，并准备好目录。

    - ``workspace``：进程根目录（一般是 cwd）。
    - 落盘目录已存在不算错误。
    """
    session_id = _new_session_id()
    session_dir = str(Path(workspace) / ".nuocode" / "sessions" / session_id)
    spill_dir = os.path.join(session_dir, "tool-results")
    Path(spill_dir).mkdir(parents=True, exist_ok=True)
    return SessionContext(session_id=session_id, session_dir=session_dir, spill_dir=spill_dir)


def open_session_context(workspace: str, session_id: str) -> SessionContext:
    """打开已有会话目录（恢复场景）：不创建目录，仅填充字段。"""
    session_dir = str(Path(workspace) / ".nuocode" / "sessions" / session_id)
    spill_dir = os.path.join(session_dir, "tool-results")
    return SessionContext(session_id=session_id, session_dir=session_dir, spill_dir=spill_dir)


def parse_session_time(session_id: str) -> datetime:
    """从 session_id 前 15 位解析 ``YYYYMMDD-HHMMSS``。

    解析失败抛 ``ValueError``（旧格式或损坏 ID）。
    """
    if len(session_id) < 15:
        raise ValueError(f"session_id 太短: {session_id!r}")
    head = session_id[:15]
    return datetime.strptime(head, "%Y%m%d-%H%M%S")


# ───────── 替换决策账本（第 1 层用） ─────────


class ContentReplacementState:
    """工具结果替换决策账本（决策一旦冻结，本会话内不翻转）。

    - ``_seen_ids``：已决策过的 tool_use_id 集合（kept 与 replaced 都进入）。
    - ``_replacements``：仅 replaced 分支的 id → 预览字符串映射。
    - ``_lock``：保护"读账本 → 决策 → 写账本"原子完成；
      ``decide_once`` 是唯一入口。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._seen_ids: set[str] = set()
        self._replacements: dict[str, str] = {}

    def is_seen(self, tool_use_id: str) -> bool:
        with self._lock:
            return tool_use_id in self._seen_ids

    def decide_once(
        self,
        tool_use_id: str,
        original_content: str,
        decide: Callable[[], tuple[str, str]],
    ) -> str:
        with self._lock:
            if tool_use_id in self._seen_ids:
                if tool_use_id in self._replacements:
                    return self._replacements[tool_use_id]
                return original_content
            decision, preview = decide()
            if decision == "kept":
                self._seen_ids.add(tool_use_id)
                return original_content
            if decision == "replaced":
                self._replacements[tool_use_id] = preview
                self._seen_ids.add(tool_use_id)
                return preview
            return original_content


# ───────── 自动熔断状态 ─────────


class AutoCompactTrackingState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._consecutive_failures = 0

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1

    def tripped(self) -> bool:
        with self._lock:
            return self._consecutive_failures >= MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES


# ───────── 文件追踪 ─────────


@dataclass
class FileReadRecord:
    path: str
    content: str
    timestamp: datetime


class RecoveryState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._files: dict[str, FileReadRecord] = {}

    def record_file(self, path: str, content: str) -> None:
        abs_path = path
        try:
            abs_path = str(Path(path).resolve())
        except OSError:
            pass
        rec = FileReadRecord(path=abs_path, content=content, timestamp=datetime.now())
        with self._lock:
            self._files[abs_path] = rec

    def snapshot(self) -> list[FileReadRecord]:
        with self._lock:
            recs = list(self._files.values())
        recs.sort(key=lambda r: r.timestamp, reverse=True)
        return [copy.copy(r) for r in recs]


__all__ = [
    "AutoCompactTrackingState",
    "ContentReplacementState",
    "FileReadRecord",
    "RecoveryState",
    "SessionContext",
    "new_session_context",
    "open_session_context",
    "parse_session_time",
]
