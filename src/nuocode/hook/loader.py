"""hook.loader: YAML 配置加载、双层合并、字段校验（chap12）。"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

from nuocode.hook.event import Event, is_blocking, parse_event
from nuocode.hook.rule import (
    Action,
    ActionType,
    AtomCondition,
    CombineMode,
    Condition,
    HttpAction,
    PromptAction,
    Rule,
    ShellAction,
    SubagentAction,
)
from nuocode.permission.matcher import compile_matcher

# ────────── 时长解析 ──────────

_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)([smh]?)$")


def _parse_duration(s: str) -> float | None:
    """解析时长字符串，返回秒数。支持 ``30s``/``5m``/``1h``/纯数字。失败返回 None。"""
    if isinstance(s, (int, float)):
        return float(s)
    if not isinstance(s, str):
        return None
    m = _DURATION_RE.match(s.strip())
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "m":
        val *= 60
    elif unit == "h":
        val *= 3600
    return val


# ────────── 原子条件编译 ──────────

def _compile_match(match_dict: Any, name: str) -> Any | None:
    """编译单条 match 描述，返回 Matcher 或 None（含错误打印）。"""
    if not isinstance(match_dict, dict):
        print(f'hook "{name}": condition match must be a mapping, skipped', file=sys.stderr)
        return None
    mtype = match_dict.get("type")
    if mtype not in ("exact", "glob", "regex", "not"):
        print(f'hook "{name}": unknown match type {mtype!r}, skipped', file=sys.stderr)
        return None
    if mtype == "not":
        inner_dict = match_dict.get("inner")
        if inner_dict is None:
            print(f'hook "{name}": "not" match missing "inner", skipped', file=sys.stderr)
            return None
        inner = _compile_match(inner_dict, name)
        if inner is None:
            return None
        from nuocode.permission.matcher import NotMatcher
        return NotMatcher(inner)
    value = match_dict.get("value")
    if value is None:
        print(f'hook "{name}": match missing "value", skipped', file=sys.stderr)
        return None
    prefix = {"exact": "=", "regex": "~", "glob": ""}.get(mtype, "")
    pattern = f"{prefix}{value}"
    try:
        return compile_matcher(pattern, is_command=False)
    except ValueError as e:
        print(f'hook "{name}": condition matcher compile failed: {e}, skipped', file=sys.stderr)
        return None


def _compile_condition(if_dict: Any, name: str) -> Condition | None | bool:
    """编译 if 块，返回 Condition / None（无条件）/ False（出错跳过）。"""
    if if_dict is None:
        return None
    if not isinstance(if_dict, dict):
        print(f'hook "{name}": "if" must be a mapping, skipped', file=sys.stderr)
        return False
    has_all = "all_of" in if_dict
    has_any = "any_of" in if_dict
    if has_all and has_any:
        print(f'hook "{name}": "if" cannot have both all_of and any_of, skipped', file=sys.stderr)
        return False
    if not has_all and not has_any:
        print(f'hook "{name}": "if" must have all_of or any_of, skipped', file=sys.stderr)
        return False
    mode = CombineMode.ALL_OF if has_all else CombineMode.ANY_OF
    raw_atoms = if_dict.get("all_of" if has_all else "any_of") or []
    if not isinstance(raw_atoms, list):
        print(f'hook "{name}": condition atoms must be a list, skipped', file=sys.stderr)
        return False
    atoms: list[AtomCondition] = []
    for atom in raw_atoms:
        if not isinstance(atom, dict):
            print(f'hook "{name}": atom condition must be a mapping, skipped', file=sys.stderr)
            return False
        field_path = atom.get("field")
        if not isinstance(field_path, str) or not field_path:
            print(f'hook "{name}": atom condition missing "field", skipped', file=sys.stderr)
            return False
        matcher = _compile_match(atom.get("match"), name)
        if matcher is None:
            return False
        atoms.append(AtomCondition(field=field_path, matcher=matcher))
    return Condition(mode=mode, atoms=atoms)


# ────────── Rule 编译 ──────────

def _compile_rule(source: str, raw: Any) -> Rule | None:
    """把单条 hook dict 编译为 Rule；失败打 stderr 并返回 None。"""
    if not isinstance(raw, dict):
        print(f'[hooks] rule is not a mapping in {source}, skipped', file=sys.stderr)
        return None

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        print(f'[hooks] rule missing required "name" field in {source}, skipped', file=sys.stderr)
        return None
    name = name.strip()

    event_str = raw.get("event")
    if not isinstance(event_str, str):
        print(f'hook "{name}": missing "event" field, skipped', file=sys.stderr)
        return None
    event = parse_event(event_str)
    if event is None:
        print(f'hook "{name}": unknown event {event_str!r}, skipped', file=sys.stderr)
        return None

    # async 字段
    asyncio_mode = bool(raw.get("async", False))
    if asyncio_mode and is_blocking(event):
        print(
            f'hook "{name}": async not allowed for blocking events, skipped',
            file=sys.stderr,
        )
        return None

    # only_once
    only_once = bool(raw.get("only_once", False))

    # timeout
    timeout_raw = raw.get("timeout", "30s")
    timeout_s = _parse_duration(timeout_raw)
    if timeout_s is None:
        print(f'hook "{name}": invalid timeout {timeout_raw!r}, skipped', file=sys.stderr)
        return None

    # if 条件
    cond_result = _compile_condition(raw.get("if"), name)
    if cond_result is False:
        return None
    condition = cond_result  # None 或 Condition

    # action
    action_raw = raw.get("action")
    if not isinstance(action_raw, dict):
        print(f'hook "{name}": missing or invalid "action", skipped', file=sys.stderr)
        return None
    action_type_str = action_raw.get("type")
    try:
        action_type = ActionType(action_type_str)
    except (ValueError, TypeError):
        print(f'hook "{name}": unknown action type {action_type_str!r}, skipped', file=sys.stderr)
        return None

    action: Action
    if action_type is ActionType.SHELL:
        cmd = action_raw.get("command")
        if not isinstance(cmd, str) or not cmd:
            print(f'hook "{name}": shell action missing "command", skipped', file=sys.stderr)
            return None
        action = Action(type=action_type, shell=ShellAction(command=cmd))
    elif action_type is ActionType.PROMPT:
        text = action_raw.get("text")
        if not isinstance(text, str):
            print(f'hook "{name}": prompt action missing "text", skipped', file=sys.stderr)
            return None
        action = Action(type=action_type, prompt=PromptAction(text=text))
    elif action_type is ActionType.HTTP:
        url = action_raw.get("url")
        if not isinstance(url, str) or not url:
            print(f'hook "{name}": http action missing "url", skipped', file=sys.stderr)
            return None
        method = action_raw.get("method", "POST")
        headers = action_raw.get("headers") or {}
        body = action_raw.get("body")
        action = Action(
            type=action_type,
            http=HttpAction(url=url, method=method, headers=headers, body=body),
        )
    elif action_type is ActionType.SUBAGENT:
        agent_name = action_raw.get("agent_name")
        prompt = action_raw.get("prompt")
        if not agent_name or not prompt:
            print(
                f'hook "{name}": subagent action missing "agent_name" or "prompt", skipped',
                file=sys.stderr,
            )
            return None
        action = Action(
            type=action_type,
            subagent=SubagentAction(agent_name=agent_name, prompt=prompt),
        )
    else:
        print(f'hook "{name}": unhandled action type {action_type}, skipped', file=sys.stderr)
        return None

    return Rule(
        name=name,
        event=event,
        action=action,
        condition=condition,
        only_once=only_once,
        asyncio_mode=asyncio_mode,
        timeout_s=timeout_s,
        source=source,
    )


# ────────── 主入口 ──────────

def load(project_root: str | Path) -> "Engine":  # noqa: F821
    """扫描两层 YAML，解析合并，返回 Engine。所有错误打 stderr，不抛异常。

    优先级：project_root/.nuocode/hooks.yaml > ~/.nuocode/hooks.yaml
    两层均合并（叠加），同名 hook 保留先加载者（project 先于 user）。
    """
    from nuocode.hook.engine import Engine

    candidates = [
        (str(Path(project_root) / ".nuocode" / "hooks.yaml"), "project"),
        (str(Path.home() / ".nuocode" / "hooks.yaml"), "user"),
    ]

    rules: list[Rule] = []
    seen_names: dict[str, str] = {}  # name → source
    sources: list[str] = []

    for filepath, _ in candidates:
        p = Path(filepath)
        if not p.exists():
            continue
        try:
            raw_text = p.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[hooks] cannot read {filepath}: {e}", file=sys.stderr)
            continue
        if not raw_text.strip():
            continue
        try:
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError as e:
            print(f"[hooks] YAML parse error in {filepath}: {e}", file=sys.stderr)
            continue
        if not isinstance(data, dict) or not isinstance(data.get("hooks"), list):
            print(
                f"[hooks] {filepath}: top-level must be a mapping with 'hooks' list, skipped",
                file=sys.stderr,
            )
            continue
        sources.append(filepath)
        for item in data["hooks"]:
            rule = _compile_rule(filepath, item)
            if rule is None:
                continue
            if rule.name in seen_names:
                print(
                    f'hook "{rule.name}": duplicate name (already loaded from '
                    f'{seen_names[rule.name]}), skipped',
                    file=sys.stderr,
                )
                continue
            seen_names[rule.name] = filepath
            rules.append(rule)

    return Engine(rules=rules, sources=sources)


__all__ = ["load"]
