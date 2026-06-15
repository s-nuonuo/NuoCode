"""环境信息采集与渲染。

环境段作为系统提示的「独立第二段」与可缓存的稳定模块分属不同内容块，
本身不进缓存（每轮可能变化）。
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class Environment:
    working_dir: str = ""
    platform: str = ""
    date: str = ""
    git_status: str = ""
    version: str = ""
    model: str = ""

    def render(self) -> str:
        """渲染为「环境信息」段。空值项省略。"""
        lines: list[str] = ["环境信息："]
        if self.working_dir:
            lines.append(f"- 工作目录: {self.working_dir}")
        if self.platform:
            lines.append(f"- 平台: {self.platform}")
        if self.date:
            lines.append(f"- 日期: {self.date}")
        if self.git_status:
            lines.append(f"- Git 状态: {self.git_status}")
        if self.version:
            lines.append(f"- 应用版本: {self.version}")
        if self.model:
            lines.append(f"- 当前模型: {self.model}")
        return "\n".join(lines)


def _get_cwd() -> str:
    try:
        return os.getcwd()
    except OSError:
        return ""


def _get_git_status() -> str:
    """`git status --porcelain` 摘要；非 git 目录或不可用 → 空串。"""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    out = (proc.stdout or "").strip()
    if not out:
        return "干净（无未提交变更）"
    lines = out.splitlines()
    return f"{len(lines)} 个文件有变更"


def gather_environment(version: str, model: str) -> Environment:
    """采集运行环境。任一项失败均降级为空，不抛异常。"""
    return Environment(
        working_dir=_get_cwd(),
        platform=sys.platform,
        date=datetime.date.today().isoformat(),
        git_status=_get_git_status(),
        version=version,
        model=model,
    )


__all__ = ["Environment", "gather_environment"]
