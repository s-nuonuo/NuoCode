"""glob 工具：按 glob 模式找文件。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from nuocode.tool import Result

_MAX_RESULTS = 100


class GlobTool:
    read_only = True
    is_system = False

    def name(self) -> str:
        return "glob"

    def description(self) -> str:
        return (
            "按 glob 模式查找文件，返回匹配的路径列表（最多 100 条，按路径排序）。"
            "支持 `**` 跨层匹配，例如 `**/*.py` 找全部 Python 源文件。"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "glob 模式，例如 `**/*.py`",
                },
                "path": {
                    "type": "string",
                    "description": "搜索根目录，默认当前工作目录",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        pattern = data.get("pattern")
        if not pattern or not isinstance(pattern, str):
            return Result(content="参数 pattern 缺失或非字符串", is_error=True)
        path = data.get("path") or "."
        if not isinstance(path, str):
            return Result(content="参数 path 必须是字符串", is_error=True)

        root = Path(path)
        if not root.exists():
            return Result(content=f"搜索根目录不存在: {path}", is_error=True)

        matches: list[str] = []
        truncated = False
        try:
            count = 0
            for p in root.glob(pattern):
                if p.is_file():
                    matches.append(str(p))
                count += 1
                if count % 100 == 0:
                    await asyncio.sleep(0)
                if len(matches) > _MAX_RESULTS * 2:
                    truncated = True
                    break
        except (OSError, ValueError) as e:
            return Result(content=f"glob 失败: {e}", is_error=True)

        matches.sort()
        if len(matches) > _MAX_RESULTS:
            matches = matches[:_MAX_RESULTS]
            truncated = True

        if not matches:
            return Result(content="无匹配")
        out = "\n".join(matches)
        if truncated:
            out += "\n[truncated]"
        return Result(content=out)
