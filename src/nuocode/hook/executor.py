"""hook.executor: 四类动作执行器（shell / prompt / http / subagent stub）（chap12）。"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field

import httpx

from nuocode.hook.rule import Action, ActionType, HttpAction, Payload, PromptAction, Rule, ShellAction


def _marshal_sorted(payload: Payload) -> bytes:
    """把 payload 序列化为 key 字典序的 JSON bytes（N6）。"""
    return json.dumps(payload, sort_keys=True).encode()


@dataclass
class ExecutionResult:
    blocked: bool = False
    reason: str = ""
    prompt: str = ""            # 仅 prompt 动作非空
    err: Exception | None = None  # hook 自身失败（不拦截）


class Executor:
    """四类动作的执行入口。实例复用 httpx.AsyncClient 连接池。"""

    def __init__(self) -> None:
        self._http_client = httpx.AsyncClient(timeout=30.0)

    async def run(self, rule: Rule, payload: Payload, *, blocking: bool) -> ExecutionResult:
        """分发到各类型执行方法。"""
        action = rule.action
        if action.type is ActionType.SHELL:
            assert action.shell is not None
            return await self._run_shell(action.shell, payload, blocking, rule.timeout_s)
        if action.type is ActionType.PROMPT:
            assert action.prompt is not None
            return self._run_prompt(action.prompt)
        if action.type is ActionType.HTTP:
            assert action.http is not None
            return await self._run_http(action.http, payload, blocking, rule.timeout_s)
        if action.type is ActionType.SUBAGENT:
            assert action.subagent is not None
            return self._run_subagent(action.subagent)
        return ExecutionResult(err=RuntimeError(f"unknown action type: {action.type}"))

    # ────────── shell ──────────

    async def _run_shell(
        self,
        sa: ShellAction,
        payload: Payload,
        blocking: bool,
        timeout_s: float,
    ) -> ExecutionResult:
        proc = await asyncio.create_subprocess_shell(
            sa.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        payload_bytes = _marshal_sorted(payload)
        try:
            stdout, stderr_out = await asyncio.wait_for(
                proc.communicate(input=payload_bytes),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await proc.wait()
            except Exception:  # noqa: BLE001
                pass
            return ExecutionResult(err=TimeoutError(f"shell command timed out after {timeout_s}s"))
        except Exception as e:  # noqa: BLE001
            return ExecutionResult(err=e)

        code = proc.returncode
        if blocking and code == 2:
            # 拦截信号：stderr 优先，stderr 空则用 stdout
            raw = (stderr_out or stdout or b"").decode(errors="replace").rstrip("\n")
            return ExecutionResult(blocked=True, reason=raw)
        if code == 0:
            return ExecutionResult()
        # 其它非 0：hook 失败，不拦截
        return ExecutionResult(
            err=RuntimeError(f"exit {code}: {stderr_out.decode(errors='replace')}")
        )

    # ────────── prompt ──────────

    def _run_prompt(self, pa: PromptAction) -> ExecutionResult:
        return ExecutionResult(prompt=pa.text)

    # ────────── http ──────────

    async def _run_http(
        self,
        ha: HttpAction,
        payload: Payload,
        blocking: bool,
        timeout_s: float,
    ) -> ExecutionResult:
        method = ha.method or "POST"
        # 构造 body
        if ha.body is None:
            body_bytes = _marshal_sorted(payload)
            content_type = "application/json"
        else:
            try:
                body_str = ha.body.format_map(payload)
            except (KeyError, ValueError) as e:
                return ExecutionResult(err=RuntimeError(f"body template render failed: {e}"))
            body_bytes = body_str.encode()
            content_type = "text/plain"

        headers = dict(ha.headers)
        headers.setdefault("Content-Type", content_type)

        try:
            resp = await self._http_client.request(
                method,
                ha.url,
                content=body_bytes,
                headers=headers,
                timeout=timeout_s,
            )
        except httpx.TimeoutException as e:
            return ExecutionResult(err=e)
        except httpx.HTTPError as e:
            return ExecutionResult(err=e)
        except Exception as e:  # noqa: BLE001
            return ExecutionResult(err=e)

        # 拦截逻辑
        if blocking and resp.is_success:
            try:
                body_data = resp.json()
                if isinstance(body_data, dict) and body_data.get("decision") == "block":
                    reason = body_data.get("reason", "")
                    return ExecutionResult(blocked=True, reason=str(reason))
            except Exception:  # noqa: BLE001
                pass  # JSON 解析失败 → 放行

        return ExecutionResult()

    # ────────── subagent (stub) ──────────

    def _run_subagent(self, sa) -> ExecutionResult:  # noqa: ANN001
        print(
            f"[hook subagent] not yet implemented, skipped: {sa.agent_name}",
            file=sys.stderr,
        )
        return ExecutionResult()


__all__ = ["ExecutionResult", "Executor"]
