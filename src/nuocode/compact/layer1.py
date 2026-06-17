"""第 1 层：单条工具结果落盘 + 单轮聚合落盘 + 决策冻结。

进入约束：``offload_and_snip`` 是确定性的纯字符串处理 + 同步 I/O，
不调用 LLM。落盘失败时降级为不替换、不写账本，下次重试。
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path

from nuocode.compact.const import (
    MESSAGE_AGGREGATE_LIMIT,
    PREVIEW_HEAD_BYTES,
    PREVIEW_HEAD_LINES,
    SINGLE_RESULT_LIMIT,
)
from nuocode.compact.state import ContentReplacementState, SessionContext
from nuocode.llm import ROLE_TOOL, Message

logger = logging.getLogger(__name__)


# ───────── 落盘 ─────────


def spill_single(session: SessionContext, tool_use_id: str, content: str) -> None:
    """把单条 tool_result 内容写入 ``spill_dir/<tool_use_id>``。

    幂等：文件已存在则不重写，不报错；磁盘失败抛 ``OSError``。
    """
    path = Path(session.spill_dir) / tool_use_id
    if path.exists():
        return
    # 父目录幂等创建（new_session_context 已建过，但防御性补一次）
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


# ───────── 预览体 ─────────


def _truncate_to_bytes(s: str, limit: int) -> str:
    """按 UTF-8 字节裁剪，保证不切坏多字节字符。"""
    encoded = s.encode("utf-8")
    if len(encoded) <= limit:
        return s
    cut = encoded[:limit]
    # 沿字节回退，直到 decode 成功
    for back in range(0, 4):
        try:
            return cut[: len(cut) - back].decode("utf-8")
        except UnicodeDecodeError:
            continue
    return cut.decode("utf-8", errors="ignore")


def _head_preview(content: str) -> str:
    """先按 ``\\n`` 截到最多 ``PREVIEW_HEAD_LINES`` 行，
    再按 ``PREVIEW_HEAD_BYTES`` 做字节级二次裁剪。
    """
    lines = content.splitlines(keepends=True)
    if len(lines) > PREVIEW_HEAD_LINES:
        head = "".join(lines[:PREVIEW_HEAD_LINES])
    else:
        head = "".join(lines)
    if len(head.encode("utf-8")) > PREVIEW_HEAD_BYTES:
        head = _truncate_to_bytes(head, PREVIEW_HEAD_BYTES)
    return head


def build_preview(original_bytes: int, head: str, spill_path: str) -> str:
    """构造替换体字符串（逐字节稳定）。

    包含四项稳定标记：
    1. 原始字节数（``original size:`` 子串）。
    2. 落盘路径（``[saved to]`` 子串与 spill_path 尾段）。
    3. 头部预览（``head preview`` 子串）。
    4. 重读提示（``文件读取工具`` 与 ``不要凭头部预览猜测`` 关键短语）。
    """
    # 用 list join 避免 f-string 多行导致行尾空格不稳定
    parts = [
        f"[content offloaded] original size: {original_bytes} bytes",
        f"[saved to] {spill_path}",
        "[head preview]",
        head.rstrip("\n"),
        "完整内容已保存到上述路径，如需查看请用文件读取工具读取该路径，不要凭头部预览猜测全文。",
    ]
    return "\n".join(parts)


# ───────── 主入口 ─────────


def _content_bytes(s: str) -> int:
    return len(s.encode("utf-8"))


def offload_and_snip(
    msgs: list[Message],
    state: ContentReplacementState,
    session: SessionContext,
) -> list[Message]:
    """对每条 ROLE_TOOL 消息上的 ``tool_results`` 做"超阈值落盘 + 字符串替换"。

    规则：
    1. 已 Seen 的项直接通过 ``state.decide_once`` 复用账本结果（不再构造预览）。
    2. 未决策的项按字节倒序处理：单条 > ``SINGLE_RESULT_LIMIT`` 必落盘；
       否则按"剩余聚合 > ``MESSAGE_AGGREGATE_LIMIT``"继续落盘下一项。
    3. 落盘失败时回退到 ``"skip"`` 决策，账本不写，下轮重试。
    4. 函数纯函数风格：返回新的 ``list[Message]``，不修改入参。
    """
    out: list[Message] = copy.deepcopy(msgs)

    for m in out:
        if m.role != ROLE_TOOL:
            continue
        results = m.tool_results or []
        if not results:
            continue

        # ── 第一遍：让账本接管已 Seen 的项（kept 返回原文，replaced 返回预览） ──
        undecided_idx: list[int] = []
        for idx, r in enumerate(results):
            id_ = r.tool_call_id
            if state.is_seen(id_):
                # 直接走账本，replaced 项返回预览，kept 项返回原文（用一个 no-op 回调）
                content = r.content or ""

                def _noop(_c=content):
                    return ("kept", "")

                new_content = state.decide_once(id_, content, _noop)
                if new_content != content:
                    results[idx] = _replace_content(r, new_content)
            else:
                undecided_idx.append(idx)

        if not undecided_idx:
            m.tool_results = results
            continue

        # ── 第二遍：未决策项按字节倒序，做单条 + 聚合判断 ──
        candidates = [(i, _content_bytes(results[i].content or "")) for i in undecided_idx]
        candidates.sort(key=lambda x: x[1], reverse=True)

        # 未落盘项的剩余聚合字节数：初值 = 所有 undecided 项之和
        remaining_agg = sum(b for _, b in candidates)

        for idx, size in candidates:
            r = results[idx]
            id_ = r.tool_call_id
            content = r.content or ""

            need_offload = size > SINGLE_RESULT_LIMIT or remaining_agg > MESSAGE_AGGREGATE_LIMIT

            if need_offload:

                def _decide(_id=id_, _content=content, _size=size):
                    try:
                        spill_single(session, _id, _content)
                    except OSError as exc:
                        logger.warning("spill_single failed: id=%s err=%s", _id, exc)
                        return ("skip", "")
                    spill_path = str(Path(session.spill_dir) / _id)
                    head = _head_preview(_content)
                    preview = build_preview(_size, head, spill_path)
                    return ("replaced", preview)

                new_content = state.decide_once(id_, content, _decide)
                if new_content != content:
                    # 落盘成功 → 替换 content，剩余聚合扣除该项
                    results[idx] = _replace_content(r, new_content)
                    remaining_agg -= size
                # else: skip 或 落盘失败，原文继续保留并参与下一轮重试
            else:
                # 不需落盘 → 决策为 kept，冻结到原文
                def _kept():
                    return ("kept", "")

                state.decide_once(id_, content, _kept)

        m.tool_results = results

    return out


def _replace_content(result, new_content: str):
    """返回一个 ``ToolResult`` 副本，仅替换 ``content``。"""
    # 直接构造新对象避免共享底层引用
    from nuocode.llm import ToolResult

    return ToolResult(
        tool_call_id=result.tool_call_id,
        content=new_content,
        is_error=result.is_error,
    )


__all__ = ["build_preview", "offload_and_snip", "spill_single"]
