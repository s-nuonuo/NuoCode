"""会话加载与恢复（JSONL → list[Message]）。"""

from __future__ import annotations

import json
import logging
import os

from nuocode import llm
from nuocode.session.writer import JSONL_FILENAME

logger = logging.getLogger(__name__)


def load_session(session_dir: str) -> list[llm.Message]:
    """逐行读取 conversation.jsonl，从最后一个 compact 标记之后构建消息列表。

    - 解析失败的行静默跳过
    - 末尾如果是带 tool_calls 的 assistant 但没后续 tool 消息 → 截断
    """
    path = os.path.join(session_dir, JSONL_FILENAME)
    if not os.path.isfile(path):
        return []

    raw_entries: list[dict] = []
    last_compact_idx = -1
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") == "compact":
                    last_compact_idx = len(raw_entries)
                raw_entries.append(d)
    except OSError as e:
        logger.warning("读取会话失败: %s (%s)", path, e)
        return []

    if last_compact_idx >= 0:
        # 跳过最后 compact 标记行本身
        slice_ = raw_entries[last_compact_idx + 1 :]
    else:
        slice_ = raw_entries

    msgs: list[llm.Message] = []
    for d in slice_:
        if d.get("type") == "compact":
            continue
        role = d.get("role")
        if role not in (llm.ROLE_USER, llm.ROLE_ASSISTANT, llm.ROLE_TOOL):
            continue
        tool_calls = []
        for tc in d.get("tool_calls") or []:
            try:
                tool_calls.append(
                    llm.ToolCall(
                        id=tc.get("id", ""),
                        name=tc.get("name", ""),
                        input=tc.get("input", ""),
                    )
                )
            except (TypeError, KeyError):
                continue
        tool_results = []
        for tr in d.get("tool_results") or []:
            try:
                tool_results.append(
                    llm.ToolResult(
                        tool_call_id=tr.get("tool_call_id", ""),
                        content=tr.get("content", ""),
                        is_error=bool(tr.get("is_error", False)),
                    )
                )
            except (TypeError, KeyError):
                continue
        msgs.append(
            llm.Message(
                role=role,
                content=d.get("content", "") or "",
                tool_calls=tool_calls,
                tool_results=tool_results,
            )
        )

    return _truncate_orphaned_tool_calls(msgs)


def _truncate_orphaned_tool_calls(msgs: list[llm.Message]) -> list[llm.Message]:
    """若末尾是带 tool_calls 的 assistant 但后续没有 tool 消息，截断该条。"""
    if not msgs:
        return msgs
    last = msgs[-1]
    if last.role == llm.ROLE_ASSISTANT and last.tool_calls:
        return msgs[:-1]
    return msgs


__all__ = ["load_session", "_truncate_orphaned_tool_calls"]
