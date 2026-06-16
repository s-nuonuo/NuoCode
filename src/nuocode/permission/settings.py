"""权限配置加载 + 工具映射 + 参数提取。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from nuocode.llm import ToolCall
from nuocode.permission import Category, SettingsError
from nuocode.permission.rule import Rule, RuleSet, parse_rule


@dataclass
class PermissionsBlock:
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass
class Settings:
    default_mode: str = ""
    permissions: PermissionsBlock = field(default_factory=PermissionsBlock)


def load_settings(path: str) -> Settings:
    """文件不存在→空 Settings；YAML 解析失败→抛 SettingsError（调用方降级）。"""
    p = Path(path)
    if not p.exists():
        return Settings()
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        raise SettingsError(f"读取 {path} 失败: {e}") from e
    if not raw.strip():
        return Settings()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise SettingsError(f"解析 {path} 失败: {e}") from e
    if data is None:
        return Settings()
    if not isinstance(data, dict):
        raise SettingsError(f"{path} 顶层必须是 mapping")
    s = Settings()
    dm = data.get("default_mode") or data.get("defaultMode") or ""
    if isinstance(dm, str):
        s.default_mode = dm
    perms = data.get("permissions") or {}
    if isinstance(perms, dict):
        a = perms.get("allow") or []
        d = perms.get("deny") or []
        if isinstance(a, list):
            s.permissions.allow = [x for x in a if isinstance(x, str)]
        if isinstance(d, list):
            s.permissions.deny = [x for x in d if isinstance(x, str)]
    return s


def to_rule_set(s: Settings) -> RuleSet:
    rs = RuleSet()
    for line in s.permissions.allow:
        r, ok = parse_rule(line)
        if ok:
            rs.allow.append(Rule(tool=r.tool, pattern=r.pattern, allow=True))
    for line in s.permissions.deny:
        r, ok = parse_rule(line)
        if ok:
            rs.deny.append(Rule(tool=r.tool, pattern=r.pattern, allow=False))
    return rs


_FRIENDLY = {
    "bash": "Bash",
    "read_file": "Read",
    "write_file": "Write",
    "edit_file": "Edit",
    "glob": "Glob",
    "grep": "Grep",
}


def friendly_name(internal: str) -> str:
    return _FRIENDLY.get(internal, internal)


def categorize(internal: str, read_only: bool) -> Category:
    """read_only=True 优先归 READ；否则按内部名分发；未知 / bash → EXEC（N7 最严）。"""
    if read_only:
        return Category.READ
    if internal in ("write_file", "edit_file"):
        return Category.WRITE
    # bash / 未知工具 → EXEC
    return Category.EXEC


def extract_target(call: ToolCall) -> tuple[str, bool, bool]:
    """返回 (target, is_file, ok)。

    - read_file/write_file/edit_file → path（is_file=True）
    - glob/grep → path（搜索根目录，缺省 "."；is_file=True；pattern 不入沙箱）
    - bash → command（is_file=False）
    - 未知 → ("", False, False)
    - JSON 解析失败 / 缺必填字段 → ok=False
    """
    raw = call.input
    if isinstance(raw, dict):
        data = raw
    else:
        s = raw or ""
        if not s.strip():
            data = {}
        else:
            try:
                data = json.loads(s)
            except (json.JSONDecodeError, TypeError):
                # 文件类调用方依据 ok=False 直接 Deny；bash 不 Deny 但落 Ask。
                if call.name == "bash":
                    return ("", False, False)
                return ("", True, False)
            if not isinstance(data, dict):
                if call.name == "bash":
                    return ("", False, False)
                return ("", True, False)

    name = call.name
    if name in ("read_file", "write_file", "edit_file"):
        path = data.get("path")
        if not isinstance(path, str) or not path:
            return ("", True, False)
        return (path, True, True)
    if name in ("glob", "grep"):
        path = data.get("path")
        if path is None or path == "":
            path = "."
        if not isinstance(path, str):
            return ("", True, False)
        return (path, True, True)
    if name == "bash":
        cmd = data.get("command")
        if not isinstance(cmd, str) or not cmd:
            return ("", False, False)
        return (cmd, False, True)
    # 未知工具
    return ("", False, False)


__all__ = [
    "PermissionsBlock",
    "Settings",
    "categorize",
    "extract_target",
    "friendly_name",
    "load_settings",
    "to_rule_set",
]
