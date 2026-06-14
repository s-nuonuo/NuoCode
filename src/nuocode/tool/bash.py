"""bash 工具：在工作目录执行 shell 命令，受 Registry 层超时保护。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from nuocode.tool import Result, _truncate


class BashTool:
    read_only = False

    def name(self) -> str:
        return "bash"

    def description(self) -> str:
        return (
            "在当前工作目录执行 shell 命令，返回 stdout / stderr / 退出码。"
            "用于查看目录、运行测试、执行简单脚本等。"
            "命令通过 /bin/sh -c 执行，支持管道与重定向；非零退出码不视为错误，按结果回灌。"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
            },
            "required": ["command"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        command = data.get("command")
        if not command or not isinstance(command, str):
            return Result(content="参数 command 缺失或非字符串", is_error=True)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            return Result(content=f"启动子进程失败: {e}", is_error=True)

        try:
            stdout_b, stderr_b = await proc.communicate()
        except asyncio.CancelledError:
            with _suppress_oserror():
                proc.kill()
            raise

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        text = f"exit_code: {proc.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        return Result(content=_truncate(text, max_lines=10000, max_chars=30000))


class _suppress_oserror:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return exc_type is not None and issubclass(exc_type, OSError)
