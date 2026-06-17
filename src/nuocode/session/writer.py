"""会话 JSONL 写入器：单文件追加 + flush + fsync。"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import IO

from nuocode import llm

logger = logging.getLogger(__name__)

JSONL_FILENAME = "conversation.jsonl"


@dataclass
class Entry:
    """JSONL 中一行的 dataclass 表示。"""

    role: str = ""
    content: str = ""
    tool_calls: list[dict] | None = None
    tool_results: list[dict] | None = None
    ts: int = 0
    model: str | None = None
    type: str | None = None  # 仅 compact 标记行使用


def _entry_to_jsonline(entry: Entry) -> str:
    d = asdict(entry)
    # 删除 None / 空字段（保持 JSONL 紧凑）
    cleaned = {}
    for k, v in d.items():
        if v is None:
            continue
        if k in ("tool_calls", "tool_results") and not v:
            continue
        if k == "content" and v == "" and (d.get("tool_calls") or d.get("tool_results")):
            continue
        cleaned[k] = v
    return json.dumps(cleaned, ensure_ascii=False)


def _msg_to_entry(msg: llm.Message, model: str | None, ts: int | None = None) -> Entry:
    if ts is None:
        ts = int(time.time())
    tool_calls: list[dict] | None = None
    if msg.tool_calls:
        tool_calls = [{"id": c.id, "name": c.name, "input": c.input} for c in msg.tool_calls]
    tool_results: list[dict] | None = None
    if msg.tool_results:
        tool_results = [
            {
                "tool_call_id": r.tool_call_id,
                "content": r.content,
                "is_error": r.is_error,
            }
            for r in msg.tool_results
        ]
    return Entry(
        role=msg.role,
        content=msg.content,
        tool_calls=tool_calls,
        tool_results=tool_results,
        ts=ts,
        model=model,
    )


class Writer:
    """conversation.jsonl 追加写入器。"""

    def __init__(self, session_dir: str) -> None:
        self._session_dir = session_dir
        os.makedirs(session_dir, exist_ok=True)
        self._path = os.path.join(session_dir, JSONL_FILENAME)
        self._file: IO[bytes] | None = open(self._path, "ab")
        self._lock = threading.Lock()
        self._first_written = self._has_existing_content()

    @classmethod
    def open_existing(cls, session_dir: str) -> Writer:
        """打开已有目录（恢复场景）：不创建目录。"""
        if not os.path.isdir(session_dir):
            raise FileNotFoundError(f"session_dir 不存在: {session_dir}")
        w = cls.__new__(cls)
        w._session_dir = session_dir
        w._path = os.path.join(session_dir, JSONL_FILENAME)
        w._file = open(w._path, "ab")
        w._lock = threading.Lock()
        w._first_written = True  # 恢复场景视为已有内容
        return w

    def _has_existing_content(self) -> bool:
        try:
            return os.path.getsize(self._path) > 0
        except OSError:
            return False

    @property
    def path(self) -> str:
        return self._path

    def append(self, msg: llm.Message, model: str = "", is_first: bool = False) -> None:
        """追加一条消息。

        - ``is_first=True`` 且当前文件为空时附带 ``model`` 字段（首条消息）。
        """
        eff_model = model if (is_first and not self._first_written and model) else None
        entry = _msg_to_entry(msg, eff_model)
        line = _entry_to_jsonline(entry) + "\n"
        with self._lock:
            if self._file is None:
                logger.warning("Writer 已关闭，丢弃追加")
                return
            self._file.write(line.encode("utf-8"))
            self._file.flush()
            try:
                os.fsync(self._file.fileno())
            except OSError:
                pass
            self._first_written = True

    def write_compact_marker(self) -> None:
        """写入 compact 标记行：``{"type":"compact","ts":<unix_ts>}``。"""
        line = json.dumps({"type": "compact", "ts": int(time.time())}) + "\n"
        with self._lock:
            if self._file is None:
                return
            self._file.write(line.encode("utf-8"))
            self._file.flush()
            try:
                os.fsync(self._file.fileno())
            except OSError:
                pass

    def append_all(self, msgs: list[llm.Message]) -> None:
        for m in msgs:
            self.append(m, model="", is_first=False)

    # ── Conversation 回调适配 ──

    def on_append(self, msg: llm.Message) -> None:
        """供 Conversation.on_append 直接绑定。

        会话首条消息的 model 由外部通过 ``set_model`` 提前注入。
        """
        is_first = not self._first_written
        self.append(msg, model=self._current_model, is_first=is_first)

    def on_replace(self, msgs: list[llm.Message]) -> None:
        """供 Conversation.on_replace 绑定：先写 compact 标记，再追加新消息。"""
        self.write_compact_marker()
        self.append_all(msgs)

    _current_model: str = ""

    def set_model(self, model: str) -> None:
        self._current_model = model

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                try:
                    self._file.close()
                finally:
                    self._file = None

    def __enter__(self) -> Writer:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


__all__ = ["Entry", "Writer", "JSONL_FILENAME"]
