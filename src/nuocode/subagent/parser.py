"""SubAgent 定义文件解析器（chap13）。

从 Markdown + YAML frontmatter 格式的 ``.md`` 文件解析出 ``Definition``。
格式与 skills/parser.py 类似，独立实现一份以避免互相依赖。

spec 参考：F4（定义文件格式）、F7（解析错误处理）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from nuocode.permission import Mode, parse_mode
from nuocode.subagent.definition import Definition, Source

# UTF-8 BOM（部分编辑器写入）
_UTF8_BOM = b"\xef\xbb\xbf"

# Agent 名称正则：允许首字母大写（如 Explore / Plan）或全小写（如 general-purpose）
AGENT_NAME_REGEX = re.compile(r"^[A-Za-z][A-Za-z0-9\-_]{0,31}$")

# 合法 model 值
_VALID_MODELS = {"haiku", "sonnet", "opus", "inherit", ""}


def _parse_frontmatter_and_body(data: bytes) -> tuple[dict, str]:
    """解析 Markdown frontmatter + body。

    返回 ``(frontmatter_dict, body_str)``。
    body 是去掉 frontmatter 块后的剩余内容（可能包含前导换行）。
    """
    # 去掉 BOM
    if data.startswith(_UTF8_BOM):
        data = data[len(_UTF8_BOM):]
    text = data.decode("utf-8")

    if not (text.startswith("---\n") or text.startswith("---\r\n")):
        raise ValueError("Agent 定义文件必须以 '---' frontmatter 开头")

    rest = text.split("\n", 1)[1]
    end_idx = rest.find("\n---")
    if end_idx < 0:
        raise ValueError("Agent 定义文件 frontmatter 未关闭（缺少结束 ---）")

    fm_text = rest[:end_idx]
    body_rest = rest[end_idx:]

    # body_rest 以 "\n---\n" 或 "\n---\r\n" 开头，跳过到下一行
    nl = body_rest.find("\n", 1)
    body = body_rest[nl + 1:] if nl >= 0 else ""

    meta_dict = yaml.safe_load(fm_text) or {}
    if not isinstance(meta_dict, dict):
        raise ValueError("Agent 定义文件 frontmatter 必须是 YAML mapping")

    return meta_dict, body


def parse_definition(data: bytes, file_path: str, source: Source) -> Definition:
    """从字节内容解析 Agent 定义文件，返回 ``Definition``。

    合法性检查：
    - ``name`` 非空且匹配 ``AGENT_NAME_REGEX``
    - ``description`` 非空
    - ``model`` 只能是 haiku/sonnet/opus/inherit；非法时 stderr 警告并 fallback 到 inherit
    - ``permissionMode: dontAsk`` → ``dont_ask=True``；其他非法 mode stderr 警告并 fallback 到 default

    spec F4 字段映射、F7 解析错误处理。
    """
    fm, body = _parse_frontmatter_and_body(data)

    # ── name ──
    name = str(fm.get("name") or "").strip()
    if not name:
        raise ValueError(f"{file_path}: frontmatter 缺少 name 字段")
    if not AGENT_NAME_REGEX.match(name):
        raise ValueError(
            f"{file_path}: name {name!r} 不合法（要求 [A-Za-z][A-Za-z0-9-_]{{0,31}}）"
        )

    # ── description ──
    description = str(fm.get("description") or "").strip()
    if not description:
        raise ValueError(f"{file_path}: frontmatter 缺少 description 字段（name={name!r}）")

    # ── tools / disallowedTools ──
    tools = [str(x) for x in (fm.get("tools") or [])]
    disallowed_tools = [str(x) for x in (fm.get("disallowedTools") or [])]

    # ── model ──
    model_raw = str(fm.get("model") or "").strip().lower()
    if model_raw not in _VALID_MODELS:
        print(
            f"[subagent] {file_path}: unknown model {fm.get('model')!r},"
            " defaulting to inherit",
            file=sys.stderr,
        )
        model_raw = "inherit"
    model = model_raw or "inherit"

    # ── maxTurns ──
    max_turns_raw = fm.get("maxTurns")
    try:
        max_turns = int(max_turns_raw) if max_turns_raw is not None else 0
    except (ValueError, TypeError):
        max_turns = 0

    # ── permissionMode ──
    mode_raw = str(fm.get("permissionMode") or "").strip()
    dont_ask = False
    permission_mode = Mode.DEFAULT

    if mode_raw.lower() == "dontask":
        dont_ask = True
        permission_mode = Mode.DEFAULT
    elif mode_raw:
        parsed, ok = parse_mode(mode_raw)
        if not ok:
            print(
                f"[subagent] {file_path}: unknown permissionMode {mode_raw!r},"
                " defaulting to default",
                file=sys.stderr,
            )
        permission_mode = parsed

    # ── background ──
    background = bool(fm.get("background") or False)

    return Definition(
        name=name,
        description=description,
        tools=tools,
        disallowed_tools=disallowed_tools,
        model=model,
        max_turns=max_turns,
        permission_mode=permission_mode,
        dont_ask=dont_ask,
        background=background,
        system_prompt=body,
        file_path=file_path,
        source=source,
    )


def parse_file(path: str, source: Source) -> Definition:
    """从磁盘路径读取并解析 Agent 定义文件。"""
    data = Path(path).read_bytes()
    return parse_definition(data, path, source)
