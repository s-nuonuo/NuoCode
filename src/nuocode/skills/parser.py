"""SKILL.md 与 tool.json 解析。"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import fields
from pathlib import Path

import yaml

from nuocode.skills.types import Skill, SkillMeta, SkillSource, ToolSpec

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME_RE.match(name) or len(name) > 32:
        raise ValueError(f"invalid skill name: {name!r}")


def _parse_frontmatter_and_body(data: str) -> tuple[dict, str]:
    if not data.startswith("---\n") and not data.startswith("---\r\n"):
        raise ValueError("SKILL.md must start with '---' frontmatter delimiter")
    rest = data.split("\n", 1)[1]
    end_idx = rest.find("\n---")
    if end_idx < 0:
        raise ValueError("SKILL.md frontmatter not closed")
    fm = rest[:end_idx]
    body = rest[end_idx:]
    # body 起始于 "\n---\n" 或 "\n---\r\n"，去掉到下一行
    nl = body.find("\n", 1)
    if nl < 0:
        body = ""
    else:
        body = body[nl + 1 :]
    meta_dict = yaml.safe_load(fm) or {}
    if not isinstance(meta_dict, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    return meta_dict, body


def _build_meta(meta_dict: dict) -> SkillMeta:
    known = {f.name for f in fields(SkillMeta)}
    filt = {k: v for k, v in meta_dict.items() if k in known}
    name = filt.get("name", "")
    desc = filt.get("description", "")
    if not isinstance(name, str):
        raise ValueError(f"name must be str: {name!r}")
    _validate_name(name)
    if not isinstance(desc, str) or not desc.strip():
        raise ValueError(f"description must be a non-empty string for skill {name!r}")
    mode = filt.get("mode", "inline") or "inline"
    if mode not in ("inline", "fork"):
        print(f"[skills] warn: skill {name}: unknown mode {mode!r}, fallback to inline",
              file=sys.stderr)
        mode = "inline"
    fc = filt.get("fork_context", "none") or "none"
    if fc not in ("none", "recent", "full"):
        print(f"[skills] warn: skill {name}: unknown fork_context {fc!r}, fallback to none",
              file=sys.stderr)
        fc = "none"
    allowed = filt.get("allowed_tools") or []
    if not isinstance(allowed, list):
        raise ValueError(f"allowed_tools must be a list for skill {name!r}")
    allowed = [str(x) for x in allowed]
    model = filt.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError(f"model must be a string or null for skill {name!r}")
    return SkillMeta(
        name=name,
        description=desc.strip(),
        allowed_tools=allowed,
        mode=mode,
        fork_context=fc,
        model=model,
    )


def _parse_tool_json(data: bytes, base_dir: Path) -> list[ToolSpec]:
    obj = json.loads(data.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("tool.json must be an object with 'tools' field")
    tools = obj.get("tools") or []
    if not isinstance(tools, list):
        raise ValueError("tool.json 'tools' must be a list")
    out: list[ToolSpec] = []
    for t in tools:
        if not isinstance(t, dict):
            raise ValueError("each tool entry must be an object")
        n = t.get("name")
        if not isinstance(n, str):
            raise ValueError("tool.name must be string")
        _validate_name(n)
        d = t.get("description") or ""
        schema = t.get("input_schema") or {"type": "object", "properties": {}}
        cmd = t.get("command") or []
        if not isinstance(cmd, list) or not cmd:
            raise ValueError(f"tool {n!r}: command must be non-empty list")
        out.append(
            ToolSpec(
                name=n,
                description=str(d),
                input_schema=schema if isinstance(schema, dict) else {},
                command=[str(x) for x in cmd],
                base_dir=base_dir,
            )
        )
    return out


def parse_skill_dir(dir_path: Path, source: SkillSource) -> Skill:
    p = Path(dir_path)
    skill_md = p / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"no SKILL.md in {p}")
    text = skill_md.read_text(encoding="utf-8")
    meta_dict, body = _parse_frontmatter_and_body(text)
    meta = _build_meta(meta_dict)

    tool_json = p / "tool.json"
    tool_specs: list[ToolSpec] = []
    if tool_json.is_file():
        try:
            tool_specs = _parse_tool_json(tool_json.read_bytes(), p.resolve())
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"skill {meta.name}: invalid tool.json: {e}") from e

    return Skill(
        meta=meta,
        prompt_body=body,
        source_dir=p.resolve(),
        source=source,
        tool_specs=tool_specs,
    )


__all__ = ["parse_skill_dir"]
