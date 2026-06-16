"""MCP 客户端配置：两层 YAML 加载、合并、`${VAR}` 展开、字段校验。

入口：:func:`load_config`，永不抛出。文件缺失视为空层；解析失败 stderr 告警并跳过。
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass
class ServerConfig:
    """单个 MCP server 的归一化定义（已展开 ``${VAR}``、已校验）。"""

    type: Literal["stdio", "http"]
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    """``mcp_servers`` 在内存中的归一化形式（已合并）。"""

    servers: dict[str, ServerConfig] = field(default_factory=dict)


@dataclass
class _RawServer:
    """读 YAML 阶段的中间形态：所有字段均允许缺省。"""

    type: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


def _coerce_str_list(v: Any) -> list[str]:
    if not v:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    return []


def _coerce_str_map(v: Any) -> dict[str, str]:
    if not v or not isinstance(v, dict):
        return {}
    return {str(k): str(vv) for k, vv in v.items()}


def _load_file(path: Path) -> dict[str, _RawServer]:
    """读取一层 YAML：缺失返回 ``{}``；非法 stderr 告警 + 返回 ``{}``。"""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except (OSError, yaml.YAMLError) as e:
        print(f"[mcp] warn: load {path} failed: {e}", file=sys.stderr)
        return {}
    if not isinstance(data, dict):
        return {}
    section = data.get("mcp_servers") or {}
    if not isinstance(section, dict):
        return {}
    out: dict[str, _RawServer] = {}
    for name, raw in section.items():
        if not isinstance(raw, dict):
            continue
        out[str(name)] = _RawServer(
            type=str(raw.get("type", "") or ""),
            command=str(raw.get("command", "") or ""),
            args=_coerce_str_list(raw.get("args")),
            env=_coerce_str_map(raw.get("env")),
            url=str(raw.get("url", "") or ""),
            headers=_coerce_str_map(raw.get("headers")),
        )
    return out


def _expand_vars(s: str) -> tuple[str, list[str]]:
    """把 ``${VAR}`` 替换为 ``os.environ[VAR]``；未定义→空串，记到 undefined。"""
    undefined: list[str] = []

    def _sub(m: re.Match[str]) -> str:
        var = m.group(1)
        if var in os.environ:
            return os.environ[var]
        undefined.append(var)
        return ""

    return _VAR_RE.sub(_sub, s), undefined


def _apply_expansion(name: str, srv: _RawServer) -> None:
    """对 env / headers 的值就地展开 ``${VAR}``；未定义变量同 server 同名限一次告警。"""
    warned: set[str] = set()

    def _walk(d: dict[str, str]) -> None:
        for k, v in list(d.items()):
            new_v, missing = _expand_vars(v)
            d[k] = new_v
            for var in missing:
                if var in warned:
                    continue
                warned.add(var)
                print(
                    f"[mcp] warn: undefined env var ${{{var}}} referenced by server {name}",
                    file=sys.stderr,
                )

    _walk(srv.env)
    _walk(srv.headers)


def _merge_servers(
    user: dict[str, _RawServer], project: dict[str, _RawServer]
) -> dict[str, _RawServer]:
    """按 server 名维度合并：项目级整对象覆盖用户级。"""
    merged: dict[str, _RawServer] = {}
    merged.update(user)
    merged.update(project)
    return merged


def _validate_server(name: str, srv: _RawServer) -> ServerConfig | None:
    """type/必填字段校验失败 → stderr 告警 + 返回 None。"""
    if srv.type not in ("stdio", "http"):
        print(
            f"[mcp] warn: skip server {name}: invalid type {srv.type!r}",
            file=sys.stderr,
        )
        return None
    if srv.type == "stdio":
        if not srv.command:
            print(
                f"[mcp] warn: skip server {name}: stdio server missing 'command'",
                file=sys.stderr,
            )
            return None
        return ServerConfig(
            type="stdio",
            command=srv.command,
            args=list(srv.args),
            env=dict(srv.env),
        )
    # http
    if not srv.url:
        print(
            f"[mcp] warn: skip server {name}: http server missing 'url'",
            file=sys.stderr,
        )
        return None
    return ServerConfig(
        type="http",
        url=srv.url,
        headers=dict(srv.headers),
    )


def _user_config_path() -> Path | None:
    try:
        return Path.home() / ".nuocode" / "config.yaml"
    except (RuntimeError, OSError):
        return None


def load_config(root: str) -> Config:
    """加载并合并两层 ``mcp_servers``；永不抛出。

    用户级：``~/.nuocode/config.yaml``；项目级：``<root>/.nuocode.yaml``。
    """
    user_path = _user_config_path()
    user_layer: dict[str, _RawServer] = {}
    if user_path is not None:
        user_layer = _load_file(user_path)
    project_layer = _load_file(Path(root) / ".nuocode.yaml")

    for layer in (user_layer, project_layer):
        for name, srv in layer.items():
            _apply_expansion(name, srv)

    merged = _merge_servers(user_layer, project_layer)
    cfg = Config()
    for name in sorted(merged.keys()):
        srv = merged[name]
        validated = _validate_server(name, srv)
        if validated is not None:
            cfg.servers[name] = validated
    return cfg


__all__ = [
    "Config",
    "ServerConfig",
    "load_config",
]
