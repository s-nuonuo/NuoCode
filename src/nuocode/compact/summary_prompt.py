"""第 2 层摘要的 prompt 模板与解析。"""

from __future__ import annotations

import logging
import re

from nuocode.llm import ROLE_ASSISTANT, ROLE_TOOL, ROLE_USER, Message

logger = logging.getLogger(__name__)


# 9 部分小节标题（固定字面字符串，便于解析与单测匹配）
SUMMARY_SECTIONS: tuple[str, ...] = (
    "## 1 主要请求和意图",
    "## 2 关键技术概念",
    "## 3 文件和代码段",
    "## 4 错误和修复",
    "## 5 问题解决过程",
    "## 6 所有用户消息原文",
    "## 7 待办任务",
    "## 8 当前工作（最详细）",
    "## 9 可能的下一步",
)


SUMMARY_INSTRUCTION: str = """\
你正在压缩一段编码 Agent 与用户的对话历史。请按以下两个阶段输出：

阶段一：在 <analysis> 与 </analysis> 之间写出分析草稿，可包括对历史的归纳、
重点信息的提取过程等。这部分内容会被丢弃，但请认真分析。

阶段二：在 <summary> 与 </summary> 之间写出正式摘要。正式摘要必须严格按以下
9 个固定小节顺序输出，每个小节用其完整标题作为分隔，标题之间用空行隔开：

## 1 主要请求和意图
（用户希望解决的问题、目标、约束）

## 2 关键技术概念
（涉及的库、API、设计模式、术语）

## 3 文件和代码段
（讨论或修改过的文件路径，关键片段，按时间顺序）

## 4 错误和修复
（出现过的错误信息原文，以及对应的修复方案）

## 5 问题解决过程
（思路演化、尝试过的方案、为什么放弃某条路）

## 6 所有用户消息原文
（按时间顺序逐条列出每一条 user 消息的原文，不省略，不改写；
若某条很长可分块呈现，但必须保留全部原文）

## 7 待办任务
（明确的 TODO 列表）

## 8 当前工作（最详细）
（正在做什么、停在哪一步、下一步要继续做的具体动作）

## 9 可能的下一步
（基于当前状态的合理后续动作建议）

注意：
- 不要调用任何工具，直接输出纯文本。
- 不要编造历史中不存在的细节。
- 第 6 部分必须逐条保留所有 user 消息的原文。
"""


def _serialize_message(m: Message) -> str:
    role = m.role
    parts: list[str] = []
    if role == ROLE_USER:
        parts.append(f"user: {m.content}")
    elif role == ROLE_ASSISTANT:
        parts.append(f"assistant: {m.content}")
        for c in m.tool_calls or []:
            parts.append(f"  [call {c.name} id={c.id} args={c.input}]")
    elif role == ROLE_TOOL:
        for r in m.tool_results or []:
            parts.append(f"[result id={r.tool_call_id} is_error={r.is_error}] {r.content}")
    return "\n".join(parts)


def serialize_conversation(msgs: list[Message]) -> str:
    """把对话扁平化成可读文本。

    格式约定：
    - user / assistant 行：``role: <content>``
    - assistant 工具调用：``[call <name> id=<id> args=<json>]``（每行一调用，缩进 2 空格）
    - tool 结果：``[result id=<id> is_error=<bool>] <content>``（每条一行）
    """
    return "\n".join(_serialize_message(m) for m in msgs)


def build_summary_prompt(msgs: list[Message]) -> list[Message]:
    """返回长度为 1 的列表：单条 user 消息，content 内嵌指令 + 序列化对话。"""
    serialized = serialize_conversation(msgs)
    content = SUMMARY_INSTRUCTION + "\n\n[conversation]\n" + serialized
    return [Message(role=ROLE_USER, content=content)]


_SUMMARY_RE = re.compile(r"<summary>(.*?)</summary>", re.DOTALL)


def extract_summary(raw: str) -> str:
    """从模型返回的整段文本里抠出 ``<summary>...</summary>`` 之间的正文。

    - ``<analysis>`` 部分直接丢弃。
    - 找不到时返回原文 + 一条 warning 日志，避免硬失败。
    - 多对 ``<summary>`` 时取最后一对（防止模型在 analysis 内嵌套示例标签）。
    """
    matches = _SUMMARY_RE.findall(raw)
    if not matches:
        logger.warning("summary tags not found, fallback to raw text")
        return raw
    return matches[-1].strip()


__all__ = [
    "SUMMARY_INSTRUCTION",
    "SUMMARY_SECTIONS",
    "build_summary_prompt",
    "extract_summary",
    "serialize_conversation",
]
