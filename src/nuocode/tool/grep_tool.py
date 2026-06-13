"""grep 工具：在文件内容中按正则搜索。"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from nuocode.tool import Result

_MAX_HITS = 100
_MAX_LINE_LEN = 1024 * 1024  # 1MB；超过此长度的单行标注未完整搜索


class GrepTool:
    def name(self) -> str:
        return "grep"

    def description(self) -> str:
        return (
            "按 Python 正则在文件内容中搜索，返回 `file:line:content` 的命中列表"
            "（最多 100 条）。可选 `path` 限定搜索根目录，可选 `glob` 限定文件名匹配。"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python 正则表达式"},
                "path": {
                    "type": "string",
                    "description": "搜索根目录（默认当前工作目录）",
                },
                "glob": {
                    "type": "string",
                    "description": "文件名匹配模式（可选，如 `*.py`）",
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
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return Result(content=f"正则非法: {e}", is_error=True)

        path = data.get("path") or "."
        glob_pat = data.get("glob")
        root = Path(path)
        if not root.exists():
            return Result(content=f"搜索根目录不存在: {path}", is_error=True)

        if glob_pat:
            it = root.rglob(glob_pat)
        else:
            it = root.rglob("*")

        hits: list[str] = []
        truncated = False
        notes: list[str] = []
        try:
            for p in it:
                if not p.is_file():
                    continue
                try:
                    with p.open("r", encoding="utf-8", errors="replace") as f:
                        for lineno, line in enumerate(f, 1):
                            if len(line) > _MAX_LINE_LEN:
                                notes.append(f"{p}:{lineno}: 该行过长，未完整搜索")
                                continue
                            if rx.search(line):
                                hits.append(f"{p}:{lineno}:{line.rstrip()}")
                                if len(hits) >= _MAX_HITS:
                                    truncated = True
                                    break
                except (OSError, UnicodeDecodeError):
                    continue
                await asyncio.sleep(0)
                if truncated:
                    break
        except OSError as e:
            return Result(content=f"grep 失败: {e}", is_error=True)

        if not hits and not notes:
            return Result(content="无命中")
        out_lines = hits + notes
        out = "\n".join(out_lines)
        if truncated:
            out += "\n[truncated]"
        return Result(content=out)
