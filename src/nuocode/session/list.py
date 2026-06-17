"""会话列表扫描。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nuocode.compact.state import parse_session_time
from nuocode.session.writer import JSONL_FILENAME

logger = logging.getLogger(__name__)

TITLE_MAX_LEN = 50


@dataclass
class SessionInfo:
    id: str
    title: str
    modified_at: datetime
    model: str
    size: int
    dir: str


def _truncate_title(text: str) -> str:
    text = (text or "").replace("\n", " ").strip()
    if len(text) <= TITLE_MAX_LEN:
        return text
    return text[: TITLE_MAX_LEN - 1] + "…"


def list_sessions(sessions_dir: str) -> list[SessionInfo]:
    """扫描 sessions_dir，按最后修改时间倒序返回有效会话。

    只返回包含 conversation.jsonl 且 ID 能解析为新格式的目录。
    """
    out: list[SessionInfo] = []
    p = Path(sessions_dir)
    if not p.is_dir():
        return out
    for child in p.iterdir():
        if not child.is_dir():
            continue
        try:
            parse_session_time(child.name)
        except ValueError:
            continue  # 旧格式跳过
        jsonl = child / JSONL_FILENAME
        if not jsonl.is_file():
            continue
        try:
            stat = jsonl.stat()
        except OSError:
            continue
        title, model = _peek_first_user_msg(str(jsonl))
        out.append(
            SessionInfo(
                id=child.name,
                title=title,
                modified_at=datetime.fromtimestamp(stat.st_mtime),
                model=model,
                size=stat.st_size,
                dir=str(child),
            )
        )
    out.sort(key=lambda s: s.modified_at, reverse=True)
    return out


def _peek_first_user_msg(jsonl_path: str) -> tuple[str, str]:
    """读取 JSONL 找到第一条 role==user 的消息：返回 (title, model)。"""
    title = ""
    model = ""
    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not model and isinstance(d.get("model"), str):
                    model = d["model"]
                if d.get("role") == "user" and not title:
                    title = _truncate_title(d.get("content", ""))
                if title and model:
                    break
    except OSError as e:
        logger.warning("读取会话失败: %s (%s)", jsonl_path, e)
    return title, model


__all__ = ["SessionInfo", "list_sessions"]
