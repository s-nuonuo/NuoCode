"""instructions.Loader 单测：三层加载、@include 展开、边界与异常。"""

from __future__ import annotations

from pathlib import Path

from nuocode.instructions import Loader


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_three_layer_priority(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    home = tmp_path / "home"
    _write(proj / "nuocode.md", "PROJECT_ROOT_LINE")
    _write(proj / ".nuocode" / "nuocode.md", "PROJECT_DOT_LINE")
    _write(home / ".nuocode" / "nuocode.md", "USER_LINE")
    out = Loader(str(proj), str(home)).load()
    i1 = out.index("PROJECT_ROOT_LINE")
    i2 = out.index("PROJECT_DOT_LINE")
    i3 = out.index("USER_LINE")
    assert i1 < i2 < i3


def test_missing_files_silent(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    home = tmp_path / "home"
    _write(proj / "nuocode.md", "ONLY_PROJECT")
    out = Loader(str(proj), str(home)).load()
    assert out.strip() == "ONLY_PROJECT"


def test_include_expansion(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    home = tmp_path / "home"
    _write(proj / "nuocode.md", "HEAD\n@include rules/style.md\nTAIL")
    _write(proj / "rules" / "style.md", "STYLE_BODY")
    out = Loader(str(proj), str(home)).load()
    assert "HEAD" in out and "TAIL" in out and "STYLE_BODY" in out
    # @include 行被展开
    assert "@include rules/style.md" not in out


def test_include_nested(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    home = tmp_path / "home"
    _write(proj / "nuocode.md", "@include a.md")
    _write(proj / "a.md", "A\n@include b.md")
    _write(proj / "b.md", "B")
    out = Loader(str(proj), str(home)).load()
    assert "A" in out and "B" in out


def test_include_depth_limit(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    home = tmp_path / "home"
    # nuocode.md(1) → 1.md(2) → 2.md(3) → 3.md(4) → 4.md(5) → 5.md(6, 超限)
    _write(proj / "nuocode.md", "@include 1.md")
    for i in range(1, 5):
        _write(proj / f"{i}.md", f"L{i}\n@include {i + 1}.md")
    _write(proj / "5.md", "L5")
    out = Loader(str(proj), str(home)).load()
    assert "L4" in out
    assert "超过最大嵌套深度" in out
    assert "L5" not in out


def test_include_cycle_detected(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    home = tmp_path / "home"
    _write(proj / "nuocode.md", "@include a.md")
    _write(proj / "a.md", "A\n@include b.md")
    _write(proj / "b.md", "B\n@include a.md")
    out = Loader(str(proj), str(home)).load()
    assert "A" in out and "B" in out
    assert "检测到环路" in out


def test_include_path_escape(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    home = tmp_path / "home"
    outside = tmp_path / "outside.md"
    _write(outside, "SECRET")
    _write(proj / "nuocode.md", "@include ../outside.md")
    out = Loader(str(proj), str(home)).load()
    assert "SECRET" not in out
    assert "路径超出允许范围" in out


def test_include_binary_file_skipped(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    home = tmp_path / "home"
    _write(proj / "nuocode.md", "@include data.bin")
    bin_path = proj / "data.bin"
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    bin_path.write_bytes(b"\x00\x01\x02binary")
    out = Loader(str(proj), str(home)).load()
    assert "二进制文件" in out


def test_include_inline_not_expanded(tmp_path: Path) -> None:
    """@include 不在独占行（句中出现）→ 不展开。"""
    proj = tmp_path / "proj"
    home = tmp_path / "home"
    _write(proj / "nuocode.md", "see @include x.md inside paragraph")
    _write(proj / "x.md", "X_BODY")
    out = Loader(str(proj), str(home)).load()
    assert "X_BODY" not in out
    assert "see @include x.md" in out


def test_empty_when_no_files(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    home = tmp_path / "home"
    proj.mkdir()
    out = Loader(str(proj), str(home)).load()
    assert out == ""
