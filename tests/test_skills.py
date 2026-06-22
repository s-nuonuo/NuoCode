"""skills 包冒烟测试：parser/catalog/active/render/install。"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from nuocode.skills import (
    ActiveSkills,
    Catalog,
    SkillSource,
    parse_skill_dir,
    render_body,
)
from nuocode.skills.install import install_from_url


def _write_skill(d: Path, name: str, body: str = "Body for $ARGUMENTS", **fm) -> None:
    d.mkdir(parents=True, exist_ok=True)
    fm.setdefault("name", name)
    fm.setdefault("description", f"desc for {name}")
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for x in v:
                lines.append(f"  - {x}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    (d / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")


def test_parse_minimal(tmp_path: Path) -> None:
    sd = tmp_path / "alpha"
    _write_skill(sd, "alpha")
    sk = parse_skill_dir(sd, SkillSource.USER)
    assert sk.meta.name == "alpha"
    assert sk.meta.mode == "inline"
    assert sk.meta.fork_context == "none"
    assert "Body for" in sk.prompt_body


def test_parse_invalid_name(tmp_path: Path) -> None:
    sd = tmp_path / "bad"
    _write_skill(sd, "BadName")
    with pytest.raises(ValueError):
        parse_skill_dir(sd, SkillSource.USER)


def test_render_body_with_args_and_allowed_tools(tmp_path: Path) -> None:
    sd = tmp_path / "x"
    _write_skill(sd, "x", body="hello $ARGUMENTS", allowed_tools=["bash", "read_file"])
    sk = parse_skill_dir(sd, SkillSource.USER)
    out = render_body(sk, "world")
    assert "bash, read_file" in out
    assert "hello world" in out


def test_catalog_three_layer_override(tmp_path: Path, monkeypatch) -> None:
    # 用 ~/.nuocode/skills 与 work_dir/.nuocode/skills 模拟覆盖
    home = tmp_path / "home"
    work = tmp_path / "work"
    monkeypatch.setenv("HOME", str(home))
    # \u91cd\u4ee3\u4e34\u65f6\u5916\u90e8 home\uff1a\u51fd\u6570\u5185 Path.home() \u662f HOME env
    user_dir = home / ".nuocode" / "skills" / "alpha"
    _write_skill(user_dir, "alpha", body="USER VERSION")
    proj_dir = work / ".nuocode" / "skills" / "alpha"
    _write_skill(proj_dir, "alpha", body="PROJECT VERSION")
    c = Catalog.load(work)
    sk = c.get("alpha")
    assert sk is not None
    assert "PROJECT VERSION" in sk.prompt_body


def test_active_skills_idempotent() -> None:
    a = ActiveSkills()
    a.activate("x", "BODY1")
    a.activate("x", "BODY2")
    assert a.names() == ["x"]
    assert a.snapshot()[0].body == "BODY2"
    a.clear()
    assert a.names() == []


@pytest.mark.asyncio
async def test_install_from_url_zip_slip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil/SKILL.md", "x")
    z = tmp_path / "bad.zip"
    z.write_bytes(buf.getvalue())
    c = Catalog()
    with pytest.raises(ValueError):
        await install_from_url(f"file://{z}", c, tmp_path)


@pytest.mark.asyncio
async def test_install_from_url_happy_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "hello/SKILL.md",
            "---\nname: hello\ndescription: hi\n---\n\nBody $ARGUMENTS\n",
        )
    z = tmp_path / "good.zip"
    z.write_bytes(buf.getvalue())
    c = Catalog()
    name = await install_from_url(f"file://{z}", c, tmp_path)
    assert name == "hello"
    assert c.get("hello") is not None
