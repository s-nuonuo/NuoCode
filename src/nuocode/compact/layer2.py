"""第 2 层：LLM 全量摘要 + 三段恢复 + 近期原文 + PTL 重试 + 熔断。"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from nuocode.compact.const import (
    PTL_DROP_PERCENTAGE,
    PTL_RETRY_LIMIT,
    RECENT_KEEP_MESSAGES,
    RECENT_KEEP_TOKENS,
)
from nuocode.compact.recovery import build_recovery_attachment
from nuocode.compact.summary_prompt import build_summary_prompt, extract_summary
from nuocode.compact.token import estimate_tokens, message_chars
from nuocode.llm import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    Message,
    PromptTooLongError,
    Request,
)

if TYPE_CHECKING:
    from nuocode.compact.compact import ManageInput

logger = logging.getLogger(__name__)


# ───────── 近期原文 ─────────


def pick_recent_tail(msgs: list[Message]) -> list[Message]:
    """从尾部累加，直到累计 token ≥ ``RECENT_KEEP_TOKENS`` **且**条数 ≥ ``RECENT_KEEP_MESSAGES``
    （两个下界都满足后才停手 —— 择宽语义）。

    然后做配对修正：若起点是落单的 ``tool_result``，向前推到上一个 assistant tool_use 之前。
    """
    if not msgs:
        return []
    n = len(msgs)
    accum_tokens = 0
    accum_count = 0
    start_idx = n  # 默认全部
    for i in range(n - 1, -1, -1):
        # 单条估算：用 message_chars 单条计算字节 → 除以 3.5 估 token
        single_chars = message_chars([msgs[i]])
        from nuocode.compact.const import ESTIMATE_CHARS_PER_TOKEN

        accum_tokens += math.ceil(single_chars / ESTIMATE_CHARS_PER_TOKEN)
        accum_count += 1
        start_idx = i
        if accum_tokens >= RECENT_KEEP_TOKENS and accum_count >= RECENT_KEEP_MESSAGES:
            break

    # 配对修正：起点是 tool_result 时向前推到 assistant tool_use 之前
    while start_idx < n and msgs[start_idx].role == ROLE_TOOL:
        if start_idx > 0:
            start_idx -= 1
        else:
            # 已经到头还是 tool，丢弃这条
            start_idx = 1
            break

    return list(msgs[start_idx:])


def _join_after_summary(
    summary_and_recovery: Message,
    recent: list[Message],
) -> list[Message]:
    """把摘要+恢复消息（user）与近期原文拼接，避免 user/user 连续。"""
    if not recent:
        return [summary_and_recovery]
    first = recent[0]
    if first.role == ROLE_USER:
        bridge = Message(
            role=ROLE_ASSISTANT,
            content="（已加载上下文摘要与恢复信息。请继续。）",
        )
        return [summary_and_recovery, bridge, *recent]
    if first.role == ROLE_TOOL:
        # 防御性：pick_recent_tail 应已修正；这里再丢一次
        return [summary_and_recovery, *recent[1:]] if len(recent) > 1 else [summary_and_recovery]
    return [summary_and_recovery, *recent]


# ───────── PTL 重试分组 ─────────


def group_by_user_turn(msgs: list[Message]) -> list[list[Message]]:
    """按"user 提交 → 一组 assistant/tool 往返"分组。"""
    groups: list[list[Message]] = []
    current: list[Message] = []
    for m in msgs:
        if m.role == ROLE_USER:
            if current:
                groups.append(current)
            current = [m]
        else:
            if not current:
                # 首条不是 user：单独塞进第 0 组防止丢失
                current = [m]
            else:
                current.append(m)
    if current:
        groups.append(current)
    return groups


# ───────── 摘要请求 ─────────


async def summarize_once(in_: ManageInput, msgs: list[Message]) -> str:
    """发一次摘要请求；流尾捕获 usage 但**不**回写到 ``runtime.usage_anchor``。

    错误（含 PTL）通过 ``StreamEvent.err`` 投递，本函数立即 ``raise`` 让上层判断。
    """
    req = Request(messages=build_summary_prompt(msgs), tools=[])
    text_buf: list[str] = []
    async for ev in in_.provider.stream(req):
        if ev.err is not None:
            raise ev.err
        if ev.text:
            text_buf.append(ev.text)
        # ev.usage / ev.tool_calls / ev.done 在摘要场景里都不需要回写
        if ev.done:
            break
    raw = "".join(text_buf)
    return extract_summary(raw)


async def ptl_retry(
    in_: ManageInput,
    msgs: list[Message],
    first_err: Exception,
) -> str:
    """摘要请求自身撞 PTL 时的兜底：按 user-turn 分组逐步丢最旧组。

    阶段 A：前 ``PTL_RETRY_LIMIT`` (=3) 次，每次丢最旧 1 组。
    阶段 B：之后每次丢 ``ceil(剩余组数 × PTL_DROP_PERCENTAGE)``（至少 1 组）。
    全部丢光仍 PTL：抛最近一次 err，**不**发 messages 为空的请求。
    中间任何"非 PTL"错误立即上抛。
    """
    groups = group_by_user_turn(msgs)
    last_err: Exception = first_err
    direct = 0

    while groups:
        if direct < PTL_RETRY_LIMIT:
            groups = groups[1:]
            direct += 1
        else:
            drop = max(1, math.ceil(len(groups) * PTL_DROP_PERCENTAGE))
            groups = groups[drop:]

        if not groups:
            break

        flatten: list[Message] = [m for g in groups for m in g]
        try:
            return await summarize_once(in_, flatten)
        except PromptTooLongError as e:
            last_err = e
            continue
        except Exception:
            raise

    raise last_err


# ───────── run_summary / auto_compact / force_compact ─────────


async def run_summary(in_: ManageInput) -> list[Message]:
    """共享核心：摘要 → 恢复 → 近期原文 → join。"""
    old_msgs = in_.conv.messages()
    # 入口拍快照，整个生命周期内只用这一份
    recovery_snapshot = in_.recovery.snapshot()

    try:
        summary_text = await summarize_once(in_, old_msgs)
    except PromptTooLongError as e:
        summary_text = await ptl_retry(in_, old_msgs, e)

    recovery_text = build_recovery_attachment(recovery_snapshot, list(in_.tool_defs))

    combined = "## 历史会话摘要\n" + summary_text + "\n\n" + recovery_text
    summary_msg = Message(role=ROLE_USER, content=combined)

    recent = pick_recent_tail(old_msgs)
    return _join_after_summary(summary_msg, recent)


async def auto_compact(in_: ManageInput) -> tuple[list[Message], int, int]:
    """自动路径：成功清零熔断，失败计入熔断。"""
    before_tok = in_.estimated_token
    try:
        new_msgs = await run_summary(in_)
    except Exception:
        in_.auto_tracking.record_failure()
        raise
    in_.auto_tracking.record_success()
    after_tok = estimate_tokens(0, new_msgs, 0)
    return new_msgs, before_tok, after_tok


async def force_compact(in_: ManageInput) -> tuple[list[Message], int, int]:
    """手动 / 紧急路径：不触碰熔断状态，失败也不计入。"""
    before_tok = in_.estimated_token
    new_msgs = await run_summary(in_)
    after_tok = estimate_tokens(0, new_msgs, 0)
    return new_msgs, before_tok, after_tok


__all__ = [
    "auto_compact",
    "force_compact",
    "group_by_user_turn",
    "pick_recent_tail",
    "ptl_retry",
    "run_summary",
    "summarize_once",
]
