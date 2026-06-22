"""Skill body 渲染：$ARGUMENTS 替换 + allowed_tools 顶部提示。"""

from __future__ import annotations

from nuocode.skills.types import Skill


def render_body(s: Skill, args: str) -> str:
    body = s.prompt_body
    if s.meta.allowed_tools:
        tools = ", ".join(s.meta.allowed_tools)
        prefix = (
            f"This skill is designed to use only these tools: {tools}. "
            f"Prefer them over other tools when possible.\n\n---\n\n"
        )
        body = prefix + body
    args = args or ""
    if "$ARGUMENTS" in body:
        body = body.replace("$ARGUMENTS", args)
    elif args.strip():
        body = body.rstrip() + "\n\n## User Request\n\n" + args
    return body


__all__ = ["render_body"]
