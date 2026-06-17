"""压缩后的"恢复三段"：最近读过的文件 + 当前可用工具 + 边界提示。"""

from __future__ import annotations

import json

from nuocode.compact.const import (
    ESTIMATE_CHARS_PER_TOKEN,
    RECOVERY_FILE_LIMIT,
    RECOVERY_TOKENS_PER_FILE,
)
from nuocode.compact.state import FileReadRecord
from nuocode.llm import ToolDefinition

# 边界提示固定文案（必须逐字节稳定，覆盖 prompt cache 稳定性）
BOUNDARY_NOTICE: str = (
    "需要文件原文、错误原文、用户原话时，请使用文件读取工具重新读取对应路径，"
    "不要依据摘要内容做猜测。摘要可能省略细节，原文才是事实唯一来源。"
)


def render_file_block(rec: FileReadRecord) -> str:
    """渲染单个文件快照：路径 / 时间戳 / 内容片段（必要时尾部追加截断标记）。"""
    char_limit = int(RECOVERY_TOKENS_PER_FILE * ESTIMATE_CHARS_PER_TOKEN)
    content = rec.content
    if len(content) > char_limit:
        content = content[:char_limit] + "\n(content truncated)"
    return f"### {rec.path}\n[read at] {rec.timestamp.isoformat()}\n{content}"


def render_tools_block(defs: list[ToolDefinition]) -> str:
    """渲染工具列表：每行一个工具名 + 描述，下一行展示 input_schema 的紧凑 JSON。"""
    lines: list[str] = []
    for t in defs or []:
        lines.append(f"- {t.name}: {t.description}")
        try:
            schema_json = json.dumps(t.input_schema, separators=(",", ":"), ensure_ascii=False)
        except (TypeError, ValueError):
            schema_json = str(t.input_schema)
        lines.append(f"  schema: {schema_json}")
    if not lines:
        return "(无)"
    return "\n".join(lines)


def build_recovery_attachment(
    snapshot: list[FileReadRecord],
    tool_defs: list[ToolDefinition],
) -> str:
    """构造摘要后的"恢复三段"文本片段。

    - ``snapshot``：调用方在 ``run_summary`` 入口拍好的 ``RecoveryState.snapshot()``，
      已按时间戳倒序；本函数只取前 ``RECOVERY_FILE_LIMIT`` 条。
    - ``tool_defs``：与 ``Request.tools`` 来自同一份引用的工具定义列表，
      保证恢复段宣称的工具集与下次 stream 调用严格一致。

    返回纯文本字符串。``layer2.run_summary`` 会把摘要文本与本函数输出拼到同一条
    user 消息上输出（避免 user/user 连续违反 anthropic 协议）。
    """
    parts: list[str] = []

    # ── 最近读过的文件 ──
    parts.append("## 最近读过的文件")
    files = snapshot[:RECOVERY_FILE_LIMIT]
    if not files:
        parts.append("(无)")
    else:
        for rec in files:
            parts.append(render_file_block(rec))

    # ── 当前可用工具 ──
    parts.append("")
    parts.append("## 当前可用工具")
    parts.append(render_tools_block(tool_defs))

    # ── 边界提示 ──
    parts.append("")
    parts.append("## 边界提示")
    parts.append(BOUNDARY_NOTICE)

    return "\n".join(parts)


__all__ = [
    "BOUNDARY_NOTICE",
    "build_recovery_attachment",
    "render_file_block",
    "render_tools_block",
]
