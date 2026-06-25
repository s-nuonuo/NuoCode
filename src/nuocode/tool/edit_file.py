"""edit_file 工具：唯一匹配替换。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nuocode.tool import Result
from nuocode.tool.ctx import resolve_path


class EditFileTool:
    read_only = False
    is_system = False

    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return (
            "对已有文件做唯一匹配替换：在文件中查找 `old_string`，必须恰好命中一次，"
            "替换为 `new_string` 后写回。若 0 次或多于 1 次会返回错误，"
            "请提供更长的上下文使 `old_string` 唯一。"
            "编辑前请先用 `read_file` 读取目标文件，确认 `old_string` 在文件中唯一。"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要修改的文件路径"},
                "old_string": {
                    "type": "string",
                    "description": "原文片段（必须在文件中唯一出现）",
                },
                "new_string": {"type": "string", "description": "替换后的新片段"},
            },
            "required": ["path", "old_string", "new_string"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        path = data.get("path")
        old_string = data.get("old_string")
        new_string = data.get("new_string")
        if not path or not isinstance(path, str):
            return Result(content="参数 path 缺失或非字符串", is_error=True)
        if not isinstance(old_string, str):
            return Result(content="参数 old_string 缺失或非字符串", is_error=True)
        if not isinstance(new_string, str):
            return Result(content="参数 new_string 缺失或非字符串", is_error=True)

        abs_path = resolve_path(path)
        p = Path(abs_path)
        if not p.exists() or p.is_dir():
            return Result(content=f"文件不存在或是目录: {path}", is_error=True)
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return Result(content=f"读取失败: {e}", is_error=True)

        n = content.count(old_string)
        if n == 0:
            return Result(content="未找到匹配的内容", is_error=True)
        if n > 1:
            return Result(
                content=f"匹配到 {n} 处，old_string 不唯一，请提供更长上下文使其唯一",
                is_error=True,
            )

        new_content = content.replace(old_string, new_string, 1)
        try:
            p.write_text(new_content, encoding="utf-8")
        except OSError as e:
            return Result(content=f"写回失败: {e}", is_error=True)
        return Result(content=f"已编辑 {abs_path}（替换 1 处）")

