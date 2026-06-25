"""test_worktree_slug.py：validate_slug + flat_slug 单测（chap14 T1）。"""

import pytest

from nuocode.worktree.slug import flat_slug, validate_slug


# ── 合法 slug ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("slug", [
    "alice",
    "team/alice",
    "v1.0",
    "a_b",
    "feature/my-fix",
    "a",
    "A-B-C",
    "x" * 64,        # 正好 64 字符
    "a/b/c",
    "hello.world",
    "fix_bug-123",
])
def test_valid_slugs(slug: str) -> None:
    validate_slug(slug)  # 不抛异常即通过


# ── 非法 slug ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("slug,expected_fragment", [
    ("", "不能为空"),
    ("x" * 65, "超过上限"),
    ("..", "不允许"),
    ("../etc", "不允许"),
    ("./x", "不允许"),
    ("a//b", "连续"),
    ("/x", "以 '/' 开头"),
    ("a/", "以 '/' 结尾"),
    ("a b", "非法段"),
    ("a;b", "非法段"),
    ("a@b", "非法段"),
    ("a/./b", "不允许"),
    ("a/../b", "不允许"),
])
def test_invalid_slugs(slug: str, expected_fragment: str) -> None:
    with pytest.raises(ValueError, match=expected_fragment):
        validate_slug(slug)


# ── flat_slug ──────────────────────────────────────────────────────────────

def test_flat_slug_no_slash() -> None:
    assert flat_slug("alice") == "alice"


def test_flat_slug_single_slash() -> None:
    assert flat_slug("team/alice") == "team+alice"


def test_flat_slug_multi_slash() -> None:
    assert flat_slug("a/b/c") == "a+b+c"
