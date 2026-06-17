"""compact 包对外的唯一编排入口：``manage_context``。

外部调用方（Agent 主循环 / TUI 手动入口）只通过本模块与 compact 包交互。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from nuocode.compact.const import AUTO_SAFETY_MARGIN, SUMMARY_RESERVE
from nuocode.compact.layer1 import offload_and_snip
from nuocode.compact.layer2 import auto_compact, force_compact
from nuocode.compact.state import (
    AutoCompactTrackingState,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
)
from nuocode.compact.token import estimate_tokens

if TYPE_CHECKING:
    from nuocode.conversation import Conversation
    from nuocode.llm import Provider, ToolDefinition

logger = logging.getLogger(__name__)


class TriggerKind(Enum):
    AUTO = "auto"
    MANUAL = "manual"
    EMERGENCY = "emergency"


@dataclass
class ManageInput:
    conv: Conversation
    provider: Provider
    context_window: int
    tool_defs: list[ToolDefinition]
    replacement: ContentReplacementState
    recovery: RecoveryState
    auto_tracking: AutoCompactTrackingState
    session: SessionContext
    usage_anchor: int
    anchor_msg_len: int
    estimated_token: int
    trigger: TriggerKind


@dataclass
class ManageOutput:
    before_tokens: int
    after_tokens: int


async def manage_context(in_: ManageInput) -> ManageOutput:
    """Agent 每轮请求前必调的唯一入口。

    路径决策：
    - MANUAL：跳过 layer1 / 阈值 / 熔断，直接 ``force_compact``。
    - EMERGENCY：先强制跑一次 ``offload_and_snip``，再 ``force_compact``。
    - AUTO：layer1 → 重估 → 阈值判断 → 不熔断时 ``auto_compact``。

    任一路径在拿到 new_msgs 后调 ``conv.replace_messages(new_msgs)`` 写回。
    """
    before_tok = in_.estimated_token

    if in_.trigger == TriggerKind.MANUAL:
        new_msgs, before_tok2, after_tok = await force_compact(in_)
        in_.conv.replace_messages(new_msgs)
        logger.info(
            "compact manual: before=%d after=%d", before_tok2, after_tok
        )
        return ManageOutput(before_tokens=before_tok2, after_tokens=after_tok)

    if in_.trigger == TriggerKind.EMERGENCY:
        layer1_out = offload_and_snip(in_.conv.messages(), in_.replacement, in_.session)
        in_.conv.replace_messages(layer1_out)
        new_msgs, _, after_tok = await force_compact(in_)
        in_.conv.replace_messages(new_msgs)
        logger.info(
            "compact emergency: before=%d after=%d", before_tok, after_tok
        )
        return ManageOutput(before_tokens=before_tok, after_tokens=after_tok)

    # ── AUTO 分支 ──
    layer1_out = offload_and_snip(in_.conv.messages(), in_.replacement, in_.session)
    in_.conv.replace_messages(layer1_out)

    # 用 layer1 之后的列表重估 token，避免 layer1 节省的字节不被反映
    est_tokens = estimate_tokens(in_.usage_anchor, layer1_out, in_.anchor_msg_len)

    # sanity check：context_window 太小会让阈值变负 → 死循环触发
    if in_.context_window <= SUMMARY_RESERVE + AUTO_SAFETY_MARGIN:
        logger.warning(
            "context_window=%d 过小 (≤ %d)，跳过自动 layer2",
            in_.context_window,
            SUMMARY_RESERVE + AUTO_SAFETY_MARGIN,
        )
        return ManageOutput(before_tokens=before_tok, after_tokens=est_tokens)

    threshold = in_.context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN

    if est_tokens < threshold or in_.auto_tracking.tripped():
        # 仅 layer1 生效
        return ManageOutput(before_tokens=before_tok, after_tokens=est_tokens)

    # 自动 layer2
    # 重要：把 in_.estimated_token 校准到 layer1 之后的真实估算，
    # 这样 auto_compact 内部记录的 before_tok 才与触发条件一致。
    in_.estimated_token = est_tokens
    new_msgs, _, after_tok = await auto_compact(in_)
    in_.conv.replace_messages(new_msgs)
    logger.info(
        "compact auto: before=%d after=%d", before_tok, after_tok
    )
    return ManageOutput(before_tokens=before_tok, after_tokens=after_tok)


__all__ = [
    "ManageInput",
    "ManageOutput",
    "TriggerKind",
    "manage_context",
]
