"""Team 持久化工具函数（chap15 T2、T3b）。

- sanitize：将名字规范化为路径安全字符串
- atomic_write_json：先写 .tmp 再 os.replace 原子替换
- read_json：读 JSON 文件
- reload_from_disk_locked：跨进程兜底，持锁后重读 disk members
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nuocode.team.types import Team


def sanitize(name: str) -> str:
    """将名字规范化为路径安全字符串（F5 步骤 1）。

    - 只保留 [a-zA-Z0-9._-]，其他替换为 -
    - 首尾去 -
    - 空字符串返回 ""
    """
    if not name:
        return ""
    # 替换非法字符
    result = re.sub(r"[^a-zA-Z0-9._\-]", "-", name)
    # 首尾去 -
    result = result.strip("-")
    return result


def atomic_write_json(path: str | Path, value: Any) -> None:
    """原子写 JSON 文件：先写 .tmp 再 os.replace（F8 持久化方案）。"""
    path = Path(path)
    tmp = Path(str(path) + ".tmp")
    try:
        content = json.dumps(value, indent=2, ensure_ascii=False)
        tmp.write_text(content, encoding="utf-8")
        os.replace(str(tmp), str(path))
    except Exception:
        # 清理临时文件
        try:
            tmp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        raise


def read_json(path: str | Path) -> Any:
    """读取 JSON 文件，文件不存在抛 FileNotFoundError。"""
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8"))


async def reload_from_disk_locked(team: Team) -> None:
    """跨进程兜底：在持锁后从 disk 重读 members 覆盖内存（F19c）。

    调用方必须已经持有 team._lock。
    失败时静默回退（保留内存现状）。
    """
    from nuocode.team.types import TeammateInfo

    try:
        data = read_json(team.config_path)
        members_raw = data.get("members", [])
        team.members = [TeammateInfo.from_dict(m) for m in members_raw]
    except Exception as e:  # noqa: BLE001
        print(f"[team] reload_from_disk_locked 失败，保留内存现状: {e}", file=sys.stderr)
