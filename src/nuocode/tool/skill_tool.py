"""ToolSpec 适配为 Tool 协议：通过 asyncio subprocess exec 调用外部脚本。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from nuocode.tool import DEFAULT_TIMEOUT, Result, _truncate


class _SkillSubprocessTool:
    read_only = False
    is_system = False

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict,
        command: list[str],
        base_dir: Path,
    ) -> None:
        self._name = name
        self._description = description
        self._input_schema = input_schema or {"type": "object", "properties": {}}
        self._command = list(command)
        self._base_dir = Path(base_dir)

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return self._description

    def parameters(self) -> dict[str, Any]:
        return self._input_schema

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        # 首元素如非绝对路径，相对 base_dir 解析
        argv = list(self._command)
        first = argv[0]
        first_p = Path(first)
        if not first_p.is_absolute():
            first_p = self._base_dir / first
            argv[0] = str(first_p)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(self._base_dir),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            return Result(content=f"启动子进程失败: {e}", is_error=True)
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(input=json.dumps(data).encode("utf-8")),
                timeout=DEFAULT_TIMEOUT,
            )
        except TimeoutError:
            try:
                proc.kill()
            except OSError:
                pass
            return Result(content=f"skill 工具 {self._name} 执行超时", is_error=True)
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            text = f"exit_code: {proc.returncode}\nstderr:\n{stderr}\nstdout:\n{stdout}"
            return Result(content=_truncate(text, max_lines=2000, max_chars=10000), is_error=True)
        return Result(content=_truncate(stdout, max_lines=2000, max_chars=10000))


def new_skill_tool(
    name: str,
    description: str,
    input_schema: dict,
    command: list[str],
    base_dir: Path,
):
    return _SkillSubprocessTool(name, description, input_schema, command, base_dir)


__all__ = ["new_skill_tool"]
