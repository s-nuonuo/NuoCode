"""compact 包的会话级状态对象。

包含：
- SessionContext：会话生命周期信息（session_id + spill_dir）
- ContentReplacementState：工具结果替换决策账本（决策冻结）
- AutoCompactTrackingState：自动摘要熔断计数
- FileReadRecord / RecoveryState：最近读过的文件追踪状态
"""

from __future__ import annotations

import copy
import logging
import secrets
import threading
import time
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

    - ``session_id``：进程启动时一次生成，形如 ``<unix_ts>-<short_random>``。
    - ``spill_dir``：落盘目录绝对路径字符串，
      指向 ``.nuocode/sessions/<session_id>/tool-results/``。
    """

    session_id: str
    spill_dir: str


def _new_session_id() -> str:
    """生成会话 id：``<unix_ts>-<8字符 hex>``。"""
    try:
        hex_str = secrets.token_hex(4)
    except Exception:  # noqa: BLE001  - 极少触发，做兜底
        import random

        logger.warning("secrets.token_hex 失败，降级到 random.Random")
        hex_str = random.Random(time.time()).randbytes(4).hex()
    return f"{int(time.time())}-{hex_str}"


def new_session_context(workspace: str) -> SessionContext:
    """创建一个新会话上下文，并准备好 spill 目录。

    - ``workspace``：进程根目录（一般是 cwd）。
    - 落盘目录已存在不算错误。
    """
    session_id = _new_session_id()
    spill_dir = str(Path(workspace) / ".nuocode" / "sessions" / session_id / "tool-results")
    Path(spill_dir).mkdir(parents=True, exist_ok=True)
    return SessionContext(session_id=session_id, spill_dir=spill_dir)


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
        """已决策过返回 True；未 Seen 返回 False。

        仅供调用方（``offload_and_snip``）做"是否需要进入候选列表"的预判，
        不暴露替换内容。
        """
        with self._lock:
            return tool_use_id in self._seen_ids

    def decide_once(
        self,
        tool_use_id: str,
        original_content: str,
        decide: Callable[[], tuple[str, str]],
    ) -> str:
        """持锁完成"查账本 → 决策 → 写账本"。

        若 ``tool_use_id`` 已 Seen：直接返回账本中存量结果；
        - 在 ``_replacements`` 中：返回 ``_replacements[id]``（**不重新构造**）。
        - 否则：返回 ``original_content``（kept）。

        若未 Seen：调 ``decide()``（仍持锁）：
        - 返回 ``("kept", _)``：写 ``_seen_ids``，不写 ``_replacements``，返回原 content。
        - 返回 ``("replaced", preview)``：同时写 ``_seen_ids`` 与 ``_replacements[id] = preview``，返回 preview。
        - 返回 ``("skip", _)``：既不写 ``_seen_ids`` 也不写 ``_replacements``，返回原 content（下一轮重试）。
        """
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
                # 同一临界区内同时写两本，避免"已 Seen 但 replacement 未写"的中间态
                self._replacements[tool_use_id] = preview
                self._seen_ids.add(tool_use_id)
                return preview
            # skip：保持原文，账本不写
            return original_content


# ───────── 自动熔断状态 ─────────


class AutoCompactTrackingState:
    """自动摘要的连续失败计数 + 熔断标记。

    手动 / 紧急路径不读这个对象；本类只服务 ``manage_context`` 的 AUTO 分支。
    """

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
    """最近一次成功读取的文件快照。

    - ``path``：绝对路径字符串。
    - ``content``：纯净字节解码（不带行号前缀）。
    - ``timestamp``：最后一次读取时刻。
    """

    path: str
    content: str
    timestamp: datetime


class RecoveryState:
    """文件追踪：Agent 主循环写、compact 摘要时读。

    键统一用绝对路径，避免 cwd 变化导致同一文件出现两份。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._files: dict[str, FileReadRecord] = {}

    def record_file(self, path: str, content: str) -> None:
        abs_path = path
        try:
            abs_path = str(Path(path).resolve())
        except OSError:
            # 路径解析失败时仍以入参为键，保持调用不抛
            pass
        rec = FileReadRecord(path=abs_path, content=content, timestamp=datetime.now())
        with self._lock:
            self._files[abs_path] = rec

    def snapshot(self) -> list[FileReadRecord]:
        """返回按 timestamp 倒序排序的拷贝列表。"""
        with self._lock:
            recs = list(self._files.values())
        recs.sort(key=lambda r: r.timestamp, reverse=True)
        # FileReadRecord 字段都是不可变类型，浅拷贝足够
        return [copy.copy(r) for r in recs]


__all__ = [
    "AutoCompactTrackingState",
    "ContentReplacementState",
    "FileReadRecord",
    "RecoveryState",
    "SessionContext",
    "new_session_context",
]
