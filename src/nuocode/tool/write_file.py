"""write_file 工具：覆盖写文件（自动创建父目录）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nuocode.tool import Result


class WriteFileTool:
    read_only = False

    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return "覆盖写入文本文件。若父目录不存在会自动创建。用于新建文件或整体替换文件内容。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要写入的文件路径"},
                "content": {"type": "string", "description": "文件完整内容"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        path = data.get("path")
        content = data.get("content")
        if not path or not isinstance(path, str):
            return Result(content="参数 path 缺失或非字符串", is_error=True)
        if content is None or not isinstance(content, str):
            return Result(content="参数 content 缺失或非字符串", is_error=True)
        p = Path(path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except OSError as e:
            return Result(content=f"写入失败: {e}", is_error=True)
        return Result(content=f"已写入 {path}（{len(content.encode('utf-8'))} 字节）")
