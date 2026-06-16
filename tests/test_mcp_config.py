"""tests for nuocode.mcp.config: 两层合并 / 变量展开 / 字段校验 / 降级。"""

from __future__ import annotations

from pathlib import Path

import pytest

from nuocode.mcp.config import Config, ServerConfig, load_config


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _patch_user_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))


def test_no_files_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_user_home(monkeypatch, tmp_path / "home")
    cfg = load_config(str(tmp_path / "proj"))
    assert isinstance(cfg, Config)
    assert cfg.servers == {}


def test_only_project_layer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_user_home(monkeypatch, tmp_path / "home")
    proj = tmp_path / "proj"
    _write(
        proj / ".nuocode.yaml",
        """
mcp_servers:
  demo:
    type: stdio
    command: echo
    args: [hi]
""",
    )
    cfg = load_config(str(proj))
    assert "demo" in cfg.servers
    s = cfg.servers["demo"]
    assert s.type == "stdio"
    assert s.command == "echo"
    assert s.args == ["hi"]


def test_only_user_layer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    _patch_user_home(monkeypatch, home)
    _write(
        home / ".nuocode" / "config.yaml",
        """
mcp_servers:
  u:
    type: http
    url: https://x
""",
    )
    cfg = load_config(str(tmp_path / "proj"))
    assert "u" in cfg.servers
    assert cfg.servers["u"].type == "http"
    assert cfg.servers["u"].url == "https://x"


def test_project_overrides_user_full_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    _patch_user_home(monkeypatch, home)
    _write(
        home / ".nuocode" / "config.yaml",
        """
mcp_servers:
  same:
    type: stdio
    command: user-cmd
    args: [a]
""",
    )
    proj = tmp_path / "proj"
    _write(
        proj / ".nuocode.yaml",
        """
mcp_servers:
  same:
    type: stdio
    command: project-cmd
""",
    )
    cfg = load_config(str(proj))
    s = cfg.servers["same"]
    assert s.command == "project-cmd"
    # 整对象覆盖：user 的 args=[a] 不残留。
    assert s.args == []


def test_invalid_yaml_skipped_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    _patch_user_home(monkeypatch, home)
    _write(home / ".nuocode" / "config.yaml", ":not: valid: yaml::\n  -[")
    proj = tmp_path / "proj"
    _write(
        proj / ".nuocode.yaml",
        """
mcp_servers:
  ok:
    type: stdio
    command: cmd
""",
    )
    cfg = load_config(str(proj))
    err = capsys.readouterr().err
    assert "load" in err and "failed" in err
    # 项目级仍然加载成功
    assert "ok" in cfg.servers


def test_var_expansion_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_user_home(monkeypatch, tmp_path / "home")
    monkeypatch.setenv("MY_TOKEN", "secret123")
    proj = tmp_path / "proj"
    _write(
        proj / ".nuocode.yaml",
        """
mcp_servers:
  s:
    type: stdio
    command: cmd
    env:
      TOKEN: "${MY_TOKEN}"
""",
    )
    cfg = load_config(str(proj))
    assert cfg.servers["s"].env["TOKEN"] == "secret123"


def test_var_expansion_headers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_user_home(monkeypatch, tmp_path / "home")
    monkeypatch.setenv("T", "abc")
    proj = tmp_path / "proj"
    _write(
        proj / ".nuocode.yaml",
        """
mcp_servers:
  h:
    type: http
    url: https://x
    headers:
      Authorization: "Bearer ${T}"
""",
    )
    cfg = load_config(str(proj))
    assert cfg.servers["h"].headers["Authorization"] == "Bearer abc"


def test_var_undefined_warn_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_user_home(monkeypatch, tmp_path / "home")
    monkeypatch.delenv("UNDEF_X", raising=False)
    proj = tmp_path / "proj"
    _write(
        proj / ".nuocode.yaml",
        """
mcp_servers:
  s:
    type: stdio
    command: cmd
    env:
      A: "${UNDEF_X}"
      B: "${UNDEF_X}"
""",
    )
    cfg = load_config(str(proj))
    assert cfg.servers["s"].env["A"] == ""
    assert cfg.servers["s"].env["B"] == ""
    err = capsys.readouterr().err
    # 同 server 同变量去重，仅一次告警。
    assert err.count("UNDEF_X") == 1


def test_command_args_not_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_user_home(monkeypatch, tmp_path / "home")
    monkeypatch.setenv("X", "should-not-leak")
    proj = tmp_path / "proj"
    _write(
        proj / ".nuocode.yaml",
        """
mcp_servers:
  s:
    type: stdio
    command: "${X}"
    args: ["${X}"]
""",
    )
    cfg = load_config(str(proj))
    s = cfg.servers["s"]
    # command/args 字面量不展开
    assert s.command == "${X}"
    assert s.args == ["${X}"]


def test_invalid_type_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_user_home(monkeypatch, tmp_path / "home")
    proj = tmp_path / "proj"
    _write(
        proj / ".nuocode.yaml",
        """
mcp_servers:
  bad:
    type: weird
    command: cmd
  good:
    type: stdio
    command: cmd
""",
    )
    cfg = load_config(str(proj))
    assert "bad" not in cfg.servers
    assert "good" in cfg.servers
    assert "skip server bad" in capsys.readouterr().err


def test_missing_required_fields_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_user_home(monkeypatch, tmp_path / "home")
    proj = tmp_path / "proj"
    _write(
        proj / ".nuocode.yaml",
        """
mcp_servers:
  no_cmd:
    type: stdio
  no_url:
    type: http
  ok_http:
    type: http
    url: https://y
""",
    )
    cfg = load_config(str(proj))
    assert "no_cmd" not in cfg.servers
    assert "no_url" not in cfg.servers
    assert "ok_http" in cfg.servers
    err = capsys.readouterr().err
    assert "no_cmd" in err
    assert "no_url" in err


def test_example_yaml_parses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_user_home(monkeypatch, tmp_path / "home")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("EXAMPLE_TOKEN", "y")
    proj = tmp_path / "proj"
    example = Path("docs/chap07/mcp-servers.example.yaml").read_text(encoding="utf-8")
    _write(proj / ".nuocode.yaml", example)
    cfg = load_config(str(proj))
    assert set(cfg.servers.keys()) == {"github", "local-sqlite", "example-http"}
    assert cfg.servers["github"].env["GITHUB_TOKEN"] == "x"
    assert cfg.servers["example-http"].headers["Authorization"] == "Bearer y"


def test_serverconfig_dataclass_basics() -> None:
    s = ServerConfig(type="stdio", command="x")
    assert s.args == []
    assert s.env == {}
