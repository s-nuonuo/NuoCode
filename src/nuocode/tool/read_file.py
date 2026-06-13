"""read_file 工具：读文件并附行号。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nuocode.tool import Result, _truncate


class ReadFileTool:
    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return (
            "读取文本文件内容，返回带行号的文本（每行 `行号<TAB>内容`）。"
            "用于查看源码、配置或任何文本资源。"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要读取的文件路径"},
            },
            "required": ["path"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        path = data.get("path")
        if not path or not isinstance(path, str):
            return Result(content="参数 path 缺失或非字符串", is_error=True)
        p = Path(path)
        if not p.exists():
            return Result(content=f"文件不存在: {path}", is_error=True)
        if p.is_dir():
            return Result(content=f"路径是目录而非文件: {path}", is_error=True)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return Result(content=f"读取失败: {e}", is_error=True)
        lines = text.splitlines()
        numbered = "\n".join(f"{n:6d}\t{line}" for n, line in enumerate(lines, 1))
        out = _truncate(numbered, max_lines=2000, max_chars=256 * 1024)
        return Result(content=out)
