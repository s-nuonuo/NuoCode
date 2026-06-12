from __future__ import annotations

from pathlib import Path

import pytest

from nuocode.config import Config, ConfigError, ProviderConfig, load


def _write(tmp_path: Path, text: str) -> str:
    f = tmp_path / "config.yaml"
    f.write_text(text, encoding="utf-8")
    return str(f)


def test_load_single_anthropic(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
providers:
  - name: claude
    protocol: anthropic
    api_key: sk-ant-xxx
    model: claude-sonnet-4
    thinking: true
""",
    )
    cfg = load(path)
    assert isinstance(cfg, Config)
    assert len(cfg.providers) == 1
    p = cfg.providers[0]
    assert isinstance(p, ProviderConfig)
    assert p.name == "claude"
    assert p.protocol == "anthropic"
    assert p.api_key == "sk-ant-xxx"
    assert p.model == "claude-sonnet-4"
    assert p.thinking is True
    assert p.base_url is None


def test_load_multi_with_base_url(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
providers:
  - name: claude
    protocol: anthropic
    api_key: k1
    model: m1
  - name: gpt
    protocol: openai
    api_key: k2
    model: m2
    base_url: https://example.com/v1
""",
    )
    cfg = load(path)
    assert len(cfg.providers) == 2
    assert cfg.providers[1].base_url == "https://example.com/v1"
    assert cfg.providers[1].thinking is False


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="配置文件不存在"):
        load(str(tmp_path / "nope.yaml"))


def test_empty_providers(tmp_path: Path) -> None:
    path = _write(tmp_path, "providers: []\n")
    with pytest.raises(ConfigError, match="providers 不能为空"):
        load(path)


def test_missing_api_key(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
providers:
  - name: x
    protocol: anthropic
    api_key: ""
    model: m
""",
    )
    with pytest.raises(ConfigError, match=r"providers\[0\]\.api_key 不能为空"):
        load(path)


def test_invalid_protocol(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
providers:
  - name: x
    protocol: gemini
    api_key: k
    model: m
""",
    )
    with pytest.raises(ConfigError, match="protocol 非法"):
        load(path)


def test_yaml_parse_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "providers: [unclosed\n")
    with pytest.raises(ConfigError, match="YAML 解析失败"):
        load(path)


def test_thinking_must_be_bool(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
providers:
  - name: x
    protocol: anthropic
    api_key: k
    model: m
    thinking: "yes"
""",
    )
    with pytest.raises(ConfigError, match="thinking 必须是布尔值"):
        load(path)
