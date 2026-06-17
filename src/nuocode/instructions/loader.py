"""三层 nuocode.md 加载与 @include 行展开。

加载顺序（高优先级在前）：
  1. ``<project_root>/nuocode.md``
  2. ``<project_root>/.nuocode/nuocode.md``
  3. ``~/.nuocode/nuocode.md``

每份指令独立递归展开 @include；项目级（1、2）的边界为 ``project_root``，
用户级（3）边界为 ``~/.nuocode/``。@include 行格式：``@include <relative_path>``
（独占一行）；不在独占行的 @include 不展开。
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_INCLUDE_RE = re.compile(r"^@include\s+(.+?)\s*$")


@dataclass
class Loader:
    project_root: str
    user_home: str = ""
    max_depth: int = 5

    def __post_init__(self) -> None:
        if not self.user_home:
            self.user_home = os.path.expanduser("~")

    def load(self) -> str:
        """按优先级加载三层指令文件，返回拼接后文本（空行分隔）。"""
        proj_boundary = str(Path(self.project_root).resolve())
        user_boundary = str(Path(self.user_home, ".nuocode").resolve())

        layers = [
            (str(Path(self.project_root) / "nuocode.md"), proj_boundary),
            (str(Path(self.project_root) / ".nuocode" / "nuocode.md"), proj_boundary),
            (str(Path(self.user_home) / ".nuocode" / "nuocode.md"), user_boundary),
        ]

        parts: list[str] = []
        for path, boundary in layers:
            text = self._load_file(path, boundary, depth=1, visited=set())
            if text.strip():
                parts.append(text)
        return "\n\n".join(parts)

    def _load_file(
        self,
        path: str,
        boundary: str,
        depth: int,
        visited: set[str],
    ) -> str:
        # 深度检查
        if depth > self.max_depth:
            return f"<!-- @include 超过最大嵌套深度，已跳过: {path} -->"

        # 路径解析与逃逸检测
        try:
            abs_path = str(Path(path).resolve())
        except OSError:
            return ""

        try:
            boundary_abs = str(Path(boundary).resolve())
        except OSError:
            boundary_abs = boundary

        if not _is_within(abs_path, boundary_abs):
            return f"<!-- @include 路径超出允许范围，已跳过: {path} -->"

        # 环路检测
        if abs_path in visited:
            return f"<!-- @include 检测到环路，已跳过: {path} -->"

        # 文件存在性
        if not os.path.isfile(abs_path):
            return ""  # 静默跳过

        # 二进制检测
        try:
            with open(abs_path, "rb") as f:
                head = f.read(512)
        except OSError as e:
            logger.warning("读取指令文件失败: %s (%s)", abs_path, e)
            return ""
        if b"\x00" in head:
            return f"<!-- @include 二进制文件，已跳过: {path} -->"

        try:
            with open(abs_path, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("读取指令文件失败: %s (%s)", abs_path, e)
            return ""

        new_visited = visited | {abs_path}
        out_lines: list[str] = []
        base_dir = os.path.dirname(abs_path)
        for line in text.splitlines():
            m = _INCLUDE_RE.match(line)
            if m is None:
                out_lines.append(line)
                continue
            rel = m.group(1).strip()
            target = rel if os.path.isabs(rel) else os.path.join(base_dir, rel)
            expanded = self._load_file(target, boundary, depth + 1, new_visited)
            out_lines.append(expanded)
        return "\n".join(out_lines)


def _is_within(path: str, boundary: str) -> bool:
    """判断 path（绝对路径）是否在 boundary 之内（含相等）。"""
    try:
        # Path.is_relative_to 在 3.9+ 可用；这里用 commonpath 兼容
        common = os.path.commonpath([path, boundary])
        return common == boundary
    except ValueError:
        # 不同盘符等场景
        return False


__all__ = ["Loader"]
