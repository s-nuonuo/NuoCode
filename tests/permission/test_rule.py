"""permission rule + settings 扩展测试（chap12 T5）。"""

from __future__ import annotations

from nuocode.permission.matcher import ExactMatcher, GlobMatcher, RegexMatcher
from nuocode.permission.rule import parse_rule


def test_parse_rule_exact() -> None:
    r, err = parse_rule("Bash(=git status)")
    assert err is None and r is not None
    assert isinstance(r.matcher, ExactMatcher)
    assert r.matcher.value == "git status"
    assert r.matcher.match("git status") is True
    assert r.matcher.match("git status -s") is False


def test_parse_rule_regex() -> None:
    r, err = parse_rule("Bash(~^npm.*)")
    assert err is None and r is not None
    assert isinstance(r.matcher, RegexMatcher)
    assert r.matcher.match("npm install") is True
    assert r.matcher.match("pip install") is False


def test_parse_rule_not_regex() -> None:
    r, err = parse_rule("Bash(!~^rm)")
    assert err is None and r is not None
    assert r.matcher.match("ls -lh") is True
    assert r.matcher.match("rm -rf .") is False


def test_parse_rule_glob_backcompat() -> None:
    """旧写法 Bash(git *) 仍可用，生成 GlobMatcher。"""
    r, err = parse_rule("Bash(git *)")
    assert err is None and r is not None
    assert isinstance(r.matcher, GlobMatcher)
    assert r.matcher.is_command is True
    assert r.raw == "git *"
    assert r.matcher.match("git status") is True
    assert r.matcher.match("npm install") is False


def test_parse_rule_write_glob_backcompat() -> None:
    """Write(**/*.py) 文件路径 glob 向后兼容。"""
    r, err = parse_rule("Write(**/*.py)")
    assert err is None and r is not None
    assert isinstance(r.matcher, GlobMatcher)
    assert r.matcher.is_command is False  # 非 Bash → path glob


def test_parse_rule_invalid_regex_returns_error() -> None:
    r, err = parse_rule("Bash(~[invalid)")
    assert r is None and err is not None and "invalid regex" in err


def test_parse_rule_missing_paren() -> None:
    r, err = parse_rule("Bash(git *")
    assert r is None and err is not None


def test_parse_rule_full_match_no_pattern() -> None:
    r, err = parse_rule("Read")
    assert err is None and r is not None and r.matcher is None


def test_to_rule_set_stderr_on_invalid(capsys) -> None:
    from nuocode.permission.settings import PermissionsBlock, Settings, to_rule_set

    s = Settings(
        permissions=PermissionsBlock(
            allow=["Bash(git *)", "Bash(~[invalid)", "Read"],
            deny=[],
        )
    )
    rs = to_rule_set(s)
    # 合法规则被保留，非法规则被跳过
    assert len(rs.allow) == 2
    tools = {r.tool for r in rs.allow}
    assert "Bash" in tools and "Read" in tools
    # stderr 含 parse failed
    captured = capsys.readouterr()
    assert "parse failed" in captured.err
    assert "~[invalid" in captured.err


def test_to_rule_set_empty_line_no_stderr(capsys) -> None:
    """空行静默跳过，不打 stderr。"""
    from nuocode.permission.settings import PermissionsBlock, Settings, to_rule_set

    s = Settings(permissions=PermissionsBlock(allow=["Bash(git *)", ""], deny=[]))
    rs = to_rule_set(s)
    assert len(rs.allow) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
