"""Token 估算：锚定真实 usage + 字符增量。"""

from __future__ import annotations

import json
import math

from nuocode.compact.const import ESTIMATE_CHARS_PER_TOKEN
from nuocode.llm import Message, Usage


def usage_anchor(u: Usage) -> int:
    """把 stream 尾事件的 usage 合并成单一锚点 int。"""
    return (
        int(getattr(u, "input_tokens", 0) or 0)
        + int(getattr(u, "output_tokens", 0) or 0)
        + int(getattr(u, "cache_read", 0) or 0)
        + int(getattr(u, "cache_write", 0) or 0)
    )


def _safe_str_bytes(s: str | None) -> int:
    if not s:
        return 0
    return len(s.encode("utf-8"))


def message_chars(msgs: list[Message]) -> int:
    """累加单段消息列表的 UTF-8 字节量。

    含：
    - 每条 ``message.content`` 的 UTF-8 字节。
    - 每个 ``tool_calls[i].input`` 序列化后的字节（若已是 str 则直接 encode）。
    - 每个 ``tool_results[i].content`` 的 UTF-8 字节。
    """
    total = 0
    for m in msgs:
        if m is None:
            continue
        total += _safe_str_bytes(getattr(m, "content", ""))
        for c in getattr(m, "tool_calls", None) or []:
            inp = getattr(c, "input", None)
            if inp is None:
                continue
            if isinstance(inp, str):
                total += _safe_str_bytes(inp)
            else:
                try:
                    total += _safe_str_bytes(json.dumps(inp, ensure_ascii=False))
                except (TypeError, ValueError):
                    total += _safe_str_bytes(str(inp))
        for r in getattr(m, "tool_results", None) or []:
            total += _safe_str_bytes(getattr(r, "content", ""))
    return total


def estimate_tokens(anchor: int, all_msgs: list[Message], anchor_msg_len: int) -> int:
    """估算"现在发请求要消耗多少 token"。

    - ``anchor``：上一次主对话路径 stream 真实 usage 之和。
    - ``all_msgs``：当前 conversation.messages() 完整列表，
      **必须**已经经过 ``offload_and_snip``（layer1）处理；否则估算偏高。
    - ``anchor_msg_len``：anchor 被记录时 ``conv.length()`` 的值；
      只对 ``all_msgs[anchor_msg_len:]`` 这段做字符增量估算，
      避免把已含在 anchor 里的历史重复计算。
    """
    start = max(0, int(anchor_msg_len))
    if start > len(all_msgs):
        tail: list[Message] = []
    else:
        tail = list(all_msgs[start:])
    chars = message_chars(tail)
    return int(anchor) + math.ceil(chars / ESTIMATE_CHARS_PER_TOKEN)


__all__ = ["estimate_tokens", "message_chars", "usage_anchor"]
