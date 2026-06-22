"""permission.Matcher 四种类型单元测试（chap12 T2）。"""

from __future__ import annotations

import pytest

from nuocode.permission.matcher import (
    ExactMatcher,
    GlobMatcher,
    NotMatcher,
    RegexMatcher,
    compile_matcher,
)


@pytest.mark.parametrize(
    "pattern, target, is_command, expected",
    [
        # ExactMatcher
        ("=git status", "git status", True, True),
        ("=git status", "git status -s", True, False),
        ("=git status", "git status", False, True),
        ("=git status", "", True, False),
        # GlobMatcher (command)
        ("git *", "git status", True, True),
        ("git *", "npm install", True, False),
        ("git *", "git push origin main", True, True),
        # GlobMatcher (path)
        ("**/*.py", "src/a/b.py", False, True),
        ("**/*.py", "src/a.txt", False, False),
        ("src/*", "src/a.py", False, True),
        ("src/*", "src/a/b.py", False, False),  # * 不跨 /
        # RegexMatcher
        ("~^npm (install|test)$", "npm install", True, True),
        ("~^npm (install|test)$", "npm test", True, True),
        ("~^npm (install|test)$", "npm run dev", True, False),
        ("~^rm", "rm -rf .", True, True),
        ("~^rm", "ls -lh", True, False),
        # NotMatcher (not exact)
        ("!=foo", "foo", True, False),
        ("!=foo", "bar", True, True),
        ("!=foo", "", True, True),
        # NotMatcher (not regex)
        ("!~^rm", "rm -rf .", True, False),
        ("!~^rm", "ls -lh", True, True),
        # NotMatcher (not glob)
        ("!git *", "git status", True, False),
        ("!git *", "npm install", True, True),
        # 空 pattern：由 Rule.matcher=None 表达，此处只测非空
        # ("", "anything", True, True),  # 空串由 parse_rule 处理，不走 compile_matcher
    ],
    ids=[
        "exact-hit",
        "exact-miss-suffix",
        "exact-path-hit",
        "exact-empty-target",
        "glob-cmd-hit",
        "glob-cmd-miss",
        "glob-cmd-multiword",
        "glob-path-star2-py",
        "glob-path-star2-txt",
        "glob-path-single-star",
        "glob-path-no-cross-slash",
        "regex-npm-install",
        "regex-npm-test",
        "regex-npm-miss",
        "regex-rm-hit",
        "regex-rm-miss",
        "not-exact-miss",
        "not-exact-hit",
        "not-exact-empty-target",
        "not-regex-rm-miss",
        "not-regex-ls-hit",
        "not-glob-git-miss",
        "not-glob-npm-hit",
        # "empty-glob-anything",
        # "empty-glob-empty",
    ],
)
def test_compile_and_match(pattern: str, target: str, is_command: bool, expected: bool) -> None:
    m = compile_matcher(pattern, is_command=is_command)
    assert m.match(target) is expected


def test_exact_matcher_str() -> None:
    assert str(ExactMatcher("foo")) == "=foo"


def test_glob_matcher_str() -> None:
    assert str(GlobMatcher("git *", True)) == "git *"


def test_regex_matcher_str() -> None:
    import re
    m = RegexMatcher("^rm", re.compile("^rm"))
    assert str(m) == "~^rm"


def test_not_matcher_str() -> None:
    inner = ExactMatcher("foo")
    assert str(NotMatcher(inner)) == "!=foo"


def test_compile_matcher_regex_invalid() -> None:
    with pytest.raises(ValueError, match="invalid regex"):
        compile_matcher("~[invalid", is_command=True)


def test_compile_matcher_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        compile_matcher("", is_command=True)


def test_not_nested_regex() -> None:
    """!~^rm: 不以 rm 起头 → 命中。"""
    m = compile_matcher("!~^rm", is_command=True)
    assert m.match("ls -lh") is True
    assert m.match("rm -rf .") is False


def test_not_double_nested() -> None:
    """!!foo → NotMatcher(NotMatcher(GlobMatcher('foo')))，即等价 foo。"""
    m = compile_matcher("!!foo", is_command=True)
    assert m.match("foo") is True
    assert m.match("bar") is False
