"""InstallSkill 核心逻辑：下载 zip + zip-slip 防护 + 解压到 ~/.nuocode/skills/。"""

from __future__ import annotations

import re
import tempfile
import urllib.request
import zipfile
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_MAX_BYTES = 50 * 1024 * 1024


def _validate_name(name: str) -> None:
    if not _NAME_RE.match(name) or len(name) > 32:
        raise ValueError(f"invalid skill name in zip top dir: {name!r}")


def _check_safe_path(name: str) -> None:
    if not name:
        raise ValueError("unsafe path in zip: empty name")
    p = Path(name)
    if p.is_absolute():
        raise ValueError(f"unsafe path in zip (absolute): {name!r}")
    parts = p.parts
    if any(part == ".." for part in parts):
        raise ValueError(f"unsafe path in zip (..): {name!r}")


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


async def _download(source: str) -> Path:
    """同步下载（在线程池里跑）；返回临时文件路径。"""
    import asyncio

    def _do() -> Path:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        try:
            with urllib.request.urlopen(source, timeout=60) as resp:  # noqa: S310
                total = 0
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_BYTES:
                        raise ValueError("zip too large (>50MB)")
                    tmp.write(chunk)
        finally:
            tmp.close()
        return Path(tmp.name)

    return await asyncio.to_thread(_do)


async def install_from_url(source: str, catalog, work_dir: Path) -> str:  # noqa: ANN001
    if not isinstance(source, str) or not source.startswith(("http://", "https://", "file://")):
        raise ValueError(f"unsupported source: {source!r}")

    tmp_path = await _download(source)
    try:
        with zipfile.ZipFile(tmp_path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if not names:
                raise ValueError("zip is empty")

            # 顶层目录名
            tops = set()
            for n in names:
                _check_safe_path(n)
                first = Path(n).parts[0]
                tops.add(first)
            if len(tops) != 1:
                raise ValueError(f"zip must contain a single top-level dir, got {sorted(tops)}")
            top = next(iter(tops))
            _validate_name(top)

            # symlink 检测
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if _is_symlink(info):
                    raise ValueError(f"unsafe path in zip (symlink): {info.filename!r}")

            target_root = Path.home() / ".nuocode" / "skills"
            target_root.mkdir(parents=True, exist_ok=True)
            target_dir = target_root / top
            # 完整 extract
            for info in zf.infolist():
                if info.is_dir():
                    continue
                _check_safe_path(info.filename)
                dest = target_root / info.filename
                # 二次校验最终路径仍在 target_root 之下
                try:
                    dest.resolve().relative_to(target_root.resolve())
                except ValueError as e:
                    raise ValueError(
                        f"unsafe path in zip (escape): {info.filename!r}"
                    ) from e
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, open(dest, "wb") as out:
                    out.write(src.read())

            if not (target_dir / "SKILL.md").is_file():
                raise ValueError(f"installed dir missing SKILL.md: {target_dir}")
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    catalog.reload(work_dir)
    return top


__all__ = ["install_from_url"]
