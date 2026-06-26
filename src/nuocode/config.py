"""配置加载与校验。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

Protocol = Literal["anthropic", "openai"]
_VALID_PROTOCOLS: set[str] = {"anthropic", "openai"}


# ───────── 协议默认 context_window（兜底值） ─────────
# 仅在配置未填 ``context_window`` 时使用。具体模型上限请通过 yaml 显式声明。

_DEFAULT_CONTEXT_WINDOW: dict[str, int] = {
    "anthropic": 200_000,
    "openai": 128_000,
}


def default_context_window(protocol: str) -> int:
    return _DEFAULT_CONTEXT_WINDOW.get(protocol, 128_000)


class ConfigError(Exception):
    """配置文件不存在、解析失败或字段非法时抛出。"""


@dataclass
class FeaturesConfig:
    """功能 feature flags（chap15 T25）。"""

    coordinator_mode: bool = False
    fork_teammate: bool = False


@dataclass
class ProviderConfig:
    name: str
    protocol: Protocol
    api_key: str
    model: str
    base_url: str | None = None
    thinking: bool = False
    # 模型上下文窗口 token 数；未配置时用 ``default_context_window(protocol)``。
    context_window: int | None = None

    def effective_context_window(self) -> int:
        """返回生效的 context_window：显式配置优先，否则取协议兜底值。"""
        if self.context_window is not None and self.context_window > 0:
            return self.context_window
        return default_context_window(self.protocol)


@dataclass
class Config:
    providers: list[ProviderConfig] = field(default_factory=list)
    # chap13：是否允许子 Agent 后台执行（N6）
    enable_subagent_background: bool = True
    # chap15：功能 feature flags
    features: FeaturesConfig = field(default_factory=FeaturesConfig)


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

        ctx_raw = item.get("context_window")
        if ctx_raw is None:
            context_window: int | None = None
        else:
            if not isinstance(ctx_raw, int) or isinstance(ctx_raw, bool) or ctx_raw <= 0:
                raise ConfigError(f"{prefix}.context_window 必须是正整数或省略")
            context_window = ctx_raw

        providers.append(
            ProviderConfig(
                name=name,
                protocol=protocol,  # type: ignore[arg-type]
                api_key=api_key,
                model=model,
                base_url=base_url,
                thinking=thinking,
                context_window=context_window,
            )
        )

    # chap13：enable_subagent_background 解析（N6）
    enable_bg_raw = raw.get("enable_subagent_background", True)
    if not isinstance(enable_bg_raw, bool):
        enable_bg_raw = True

    # chap15：features 解析（T25）
    features_raw = raw.get("features", {})
    if isinstance(features_raw, dict):
        features = FeaturesConfig(
            coordinator_mode=bool(features_raw.get("coordinator_mode", False)),
            fork_teammate=bool(features_raw.get("fork_teammate", False)),
        )
    else:
        features = FeaturesConfig()

    return Config(
        providers=providers,
        enable_subagent_background=enable_bg_raw,
        features=features,
    )


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
