"""配置加载与校验。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

Protocol = Literal["anthropic", "openai"]
_VALID_PROTOCOLS: set[str] = {"anthropic", "openai"}


class ConfigError(Exception):
    """配置文件不存在、解析失败或字段非法时抛出。"""


@dataclass
class ProviderConfig:
    name: str
    protocol: Protocol
    api_key: str
    model: str
    base_url: str | None = None
    thinking: bool = False


@dataclass
class Config:
    providers: list[ProviderConfig] = field(default_factory=list)


def _require_str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where} 不能为空")
    return value


def _from_dict(raw: Any) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("配置文件根节点必须是映射（mapping）")

    providers_raw = raw.get("providers")
    if not isinstance(providers_raw, list) or len(providers_raw) == 0:
        raise ConfigError("providers 不能为空，至少配置一个 provider")

    providers: list[ProviderConfig] = []
    for i, item in enumerate(providers_raw):
        prefix = f"providers[{i}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{prefix} 必须是映射")
        name = _require_str(item.get("name"), f"{prefix}.name")
        protocol = _require_str(item.get("protocol"), f"{prefix}.protocol")
        if protocol not in _VALID_PROTOCOLS:
            raise ConfigError(
                f"{prefix}.protocol 非法: {protocol!r}，必须是 'anthropic' 或 'openai'"
            )
        api_key = _require_str(item.get("api_key"), f"{prefix}.api_key")
        model = _require_str(item.get("model"), f"{prefix}.model")

        base_url = item.get("base_url")
        if base_url is not None and not isinstance(base_url, str):
            raise ConfigError(f"{prefix}.base_url 必须是字符串或省略")
        if isinstance(base_url, str) and not base_url:
            base_url = None

        thinking = item.get("thinking", False)
        if not isinstance(thinking, bool):
            raise ConfigError(f"{prefix}.thinking 必须是布尔值")

        providers.append(
            ProviderConfig(
                name=name,
                protocol=protocol,  # type: ignore[arg-type]
                api_key=api_key,
                model=model,
                base_url=base_url,
                thinking=thinking,
            )
        )

    return Config(providers=providers)


def load(path: str) -> Config:
    """加载并校验 YAML 配置文件。"""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"配置文件 YAML 解析失败: {e}") from e
    return _from_dict(raw)
