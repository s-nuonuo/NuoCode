"""Agent：ReAct 循环编排（chap04）+ 权限五层防御（chap06）。

每一轮：带工具定义发起请求 → 流式收集 → 若模型请求工具则执行（前置 engine.check 五层判定）
并把结果回灌进历史 → 进入下一轮；若模型给出无工具调用的纯文本，则该文本即最终答复，循环结束。

权限判定（chap06）：
- 工具执行前调用 ``engine.check(mode, call, read_only)`` 走前四层（黑名单/沙箱/规则/模式兜底）。
- Allow → 正常执行；Deny → 构造 is_error 的 ToolResult 回灌（不中断）；
- Ask → 发出 ``ApprovalRequest`` 事件并 await 用户三选一。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum

from nuocode import llm, prompt
from nuocode.conversation import Conversation
from nuocode.llm import Provider, ToolCall, ToolResult
from nuocode.permission import Engine, Mode, Outcome
from nuocode.tool import DEFAULT_TIMEOUT, Registry

logger = logging.getLogger(__name__)

# ───────── 常量 ─────────

MAX_ITERATIONS: int = 25
MAX_UNKNOWN_RUN: int = 3
PLAN_REMINDER_INTERVAL: int = 4

NOTICE_MAX_ITER = "（已达最大迭代轮数 25，自动停止；可继续发消息推进。）"
NOTICE_UNKNOWN_TOOLS = "（连续多轮只请求到未注册的工具，自动停止。）"
NOTICE_STREAM_ERR = "（请求出错，本轮已中断。）"
NOTICE_CANCELLED = "（已取消。）"


# ───────── 数据结构 ─────────


class Phase(Enum):
    START = "start"
    END = "end"


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0


@dataclass
class ToolEvent:
    name: str
    args: str = ""
    phase: Phase = Phase.START
    result: str = ""
    is_error: bool = False


@dataclass
class ApprovalRequest:
    """人在回路：等待用户三选一。

    TUI 收到后必须调 ``respond.set_result(Outcome.X)``，否则 agent 阻塞。
    取消（Esc/Ctrl+C）时 TUI 兜底 ``set_result(Outcome.DENY_ONCE)`` 再触发取消。
    """

    name: str
    args: str
    reason: str
    respond: asyncio.Future[Outcome]


@dataclass
class Event:
    text: str = ""
    tool: ToolEvent | None = None
    usage: Usage | None = None
    iter: int = 0
    notice: str = ""
    done: bool = False
    err: Exception | None = None
    approval: ApprovalRequest | None = None


# ───────── 辅助 ─────────


def _preview_args(s: str, limit: int = 80) -> str:
    s = s or ""
    s = s.replace("\n", " ").strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _ensure_final(text: str) -> str:
    if text.strip():
        return text
    return "（空回复）"


# ───────── Agent ─────────


class Agent:
    """持有 provider / registry / engine，执行 ReAct 循环。"""

    def __init__(
        self,
        provider: Provider,
        registry: Registry,
        version: str,
        engine: Engine,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._version = version
        self._engine = engine

    async def run(
        self,
        conv: Conversation,
        mode: Mode = Mode.DEFAULT,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        if cancel is None:
            cancel = asyncio.Event()

        env = prompt.gather_environment(self._version, self._provider.model)
        sys_prompt = prompt.build_system_prompt()
        env_text = env.render()

        if mode == Mode.PLAN:
            defs = self._registry.read_only_definitions()
        else:
            defs = self._registry.definitions()

        unknown_run = 0

        for it in range(1, MAX_ITERATIONS + 1):
            yield Event(iter=it)

            if cancel.is_set():
                self._finish_cancelled(conv)
                return

            reminder = ""
            if mode == Mode.PLAN:
                full = it == 1 or (it - 1) % PLAN_REMINDER_INTERVAL == 0
                reminder = prompt.plan_reminder(full)

            text_buf: list[str] = []
            calls_buf: list[ToolCall] = []
            usage_buf: list[Usage] = []
            err_holder: list[Exception] = []

            async for ev in self._stream_once(
                conv,
                defs,
                sys_prompt,
                env_text,
                reminder,
                cancel,
                text_buf,
                calls_buf,
                usage_buf,
                err_holder,
            ):
                yield ev

            if err_holder:
                yield Event(notice=NOTICE_STREAM_ERR)
                self._ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                return

            if cancel.is_set():
                self._finish_cancelled(conv)
                return

            text = "".join(text_buf)
            calls = list(calls_buf)
            usage = usage_buf[-1] if usage_buf else None

            if usage is not None:
                yield Event(usage=usage)

            if not calls:
                conv.add_assistant(_ensure_final(text))
                yield Event(done=True)
                return

            conv.add_assistant_with_tool_calls(text, calls)

            if self._all_unknown(calls):
                unknown_run += 1
            else:
                unknown_run = 0

            results: list[ToolResult | None] = [None] * len(calls)
            completed = True
            try:
                async for ev in self._execute_batched(calls, mode, cancel, results):
                    yield ev
            except asyncio.CancelledError:
                # 取消收尾
                completed = False
                for k, c in enumerate(calls):
                    if results[k] is None:
                        results[k] = ToolResult(
                            tool_call_id=c.id, content=NOTICE_CANCELLED, is_error=True
                        )
                real_results: list[ToolResult] = [r for r in results if r is not None]
                conv.add_tool_results(real_results)
                self._ensure_assistant_tail(conv, NOTICE_CANCELLED)
                raise

            if any(r is None for r in results):
                completed = False
                for k, c in enumerate(calls):
                    if results[k] is None:
                        results[k] = ToolResult(
                            tool_call_id=c.id, content=NOTICE_CANCELLED, is_error=True
                        )

            real_results = [r for r in results if r is not None]
            conv.add_tool_results(real_results)

            if not completed:
                self._ensure_assistant_tail(conv, NOTICE_CANCELLED)
                return

            if unknown_run >= MAX_UNKNOWN_RUN:
                yield Event(notice=NOTICE_UNKNOWN_TOOLS)
                self._ensure_assistant_tail(conv, NOTICE_UNKNOWN_TOOLS)
                yield Event(done=True)
                return

        yield Event(notice=NOTICE_MAX_ITER)
        self._ensure_assistant_tail(conv, NOTICE_MAX_ITER)
        yield Event(done=True)

    async def _stream_once(
        self,
        conv: Conversation,
        defs,
        sys_prompt: str,
        env_text: str,
        reminder: str,
        cancel: asyncio.Event,
        text_buf: list[str],
        calls_buf: list[ToolCall],
        usage_buf: list[Usage],
        err_holder: list[Exception],
    ) -> AsyncIterator[Event]:
        req = llm.Request(
            messages=conv.messages(),
            tools=defs,
            system=llm.System(stable=sys_prompt, environment=env_text),
            reminder=reminder,
        )
        try:
            async for ev in self._provider.stream(req):
                if cancel.is_set():
                    return
                if ev.err is not None:
                    err_holder.append(ev.err)
                    yield Event(err=ev.err)
                    return
                if ev.text:
                    text_buf.append(ev.text)
                    yield Event(text=ev.text)
                if ev.tool_calls:
                    calls_buf.extend(ev.tool_calls)
                if ev.usage is not None:
                    usage_buf.append(
                        Usage(
                            input=ev.usage.input_tokens,
                            output=ev.usage.output_tokens,
                            cache_write=ev.usage.cache_write,
                            cache_read=ev.usage.cache_read,
                        )
                    )
                if ev.done:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            err_holder.append(e)
            yield Event(err=e)

    async def _execute_batched(
        self,
        calls: list[ToolCall],
        mode: Mode,
        cancel: asyncio.Event,
        results: list[ToolResult | None],
    ) -> AsyncIterator[Event]:
        """保序分批：连续只读并发；有副作用串行；事件 START/END 按调用序。"""
        from nuocode.permission import Decision

        i = 0
        n = len(calls)
        while i < n:
            if cancel.is_set():
                return
            if self._registry.is_read_only(calls[i].name):
                # 吃最长连续只读区间
                j = i
                while j < n and self._registry.is_read_only(calls[j].name):
                    j += 1

                previews = [_preview_args(calls[k].input) for k in range(i, j)]
                # 先为每个只读调用做权限预判（只读永不 Ask；可能 Allow / Deny）
                decisions: list[tuple[Decision, str]] = []
                for k in range(i, j):
                    decisions.append(self._engine.check(mode, calls[k], True))

                # 按序发 PHASE_START
                for k in range(i, j):
                    yield Event(
                        tool=ToolEvent(
                            name=calls[k].name,
                            args=previews[k - i],
                            phase=Phase.START,
                        )
                    )

                # 分流：Allow 进 gather；Deny 直接置结果
                tasks: dict[int, asyncio.Task] = {}
                for k in range(i, j):
                    d, reason = decisions[k - i]
                    if d == Decision.DENY:
                        results[k] = ToolResult(
                            tool_call_id=calls[k].id, content=reason, is_error=True
                        )
                    else:
                        tasks[k] = asyncio.create_task(self._run_one(calls[k]))
                if tasks:
                    gathered = await asyncio.gather(*tasks.values(), return_exceptions=False)
                    for k, res in zip(tasks.keys(), gathered, strict=True):
                        results[k] = ToolResult(
                            tool_call_id=calls[k].id,
                            content=res.content,
                            is_error=res.is_error,
                        )

                # 按序发 PHASE_END
                for k in range(i, j):
                    r = results[k]
                    assert r is not None
                    yield Event(
                        tool=ToolEvent(
                            name=calls[k].name,
                            args=previews[k - i],
                            phase=Phase.END,
                            result=r.content,
                            is_error=r.is_error,
                        )
                    )
                i = j
            else:
                # 串行单个：先权限判定
                preview = _preview_args(calls[i].input)
                yield Event(tool=ToolEvent(name=calls[i].name, args=preview, phase=Phase.START))

                decision, reason = self._engine.check(mode, calls[i], False)

                if decision == Decision.ALLOW:
                    res = await self._run_one(calls[i])
                    results[i] = ToolResult(
                        tool_call_id=calls[i].id,
                        content=res.content,
                        is_error=res.is_error,
                    )
                elif decision == Decision.DENY:
                    results[i] = ToolResult(tool_call_id=calls[i].id, content=reason, is_error=True)
                else:
                    # Ask：人在回路 —— 在 generator 内 yield ApprovalRequest 事件
                    loop = asyncio.get_running_loop()
                    respond: asyncio.Future[Outcome] = loop.create_future()
                    req = ApprovalRequest(
                        name=calls[i].name,
                        args=preview,
                        reason=reason,
                        respond=respond,
                    )
                    yield Event(approval=req)
                    try:
                        outcome = await respond
                    except asyncio.CancelledError:
                        # 上层会捕获 → 取消收尾
                        raise
                    if outcome == Outcome.DENY_ONCE:
                        results[i] = ToolResult(
                            tool_call_id=calls[i].id,
                            content=f"用户拒绝此次工具调用：{reason}",
                            is_error=True,
                        )
                    else:
                        if outcome == Outcome.ALLOW_FOREVER:
                            try:
                                self._engine.persist_local_allow(calls[i])
                            except Exception as e:  # noqa: BLE001
                                logger.warning("写入永久放行规则失败: %s", e)
                        res = await self._run_one(calls[i])
                        results[i] = ToolResult(
                            tool_call_id=calls[i].id,
                            content=res.content,
                            is_error=res.is_error,
                        )

                r = results[i]
                assert r is not None
                yield Event(
                    tool=ToolEvent(
                        name=calls[i].name,
                        args=preview,
                        phase=Phase.END,
                        result=r.content,
                        is_error=r.is_error,
                    )
                )
                i += 1

    async def _run_one(self, call: ToolCall):
        return await self._registry.execute(call.name, call.input, timeout=DEFAULT_TIMEOUT)

    def _all_unknown(self, calls: list[ToolCall]) -> bool:
        for c in calls:
            if self._registry.get(c.name) is not None:
                return False
        return True

    def _ensure_assistant_tail(self, conv: Conversation, fallback: str) -> None:
        if conv.last_role() != "assistant":
            conv.add_assistant(fallback)

    def _finish_cancelled(self, conv: Conversation) -> None:
        self._ensure_assistant_tail(conv, NOTICE_CANCELLED)


__all__ = [
    "MAX_ITERATIONS",
    "MAX_UNKNOWN_RUN",
    "PLAN_REMINDER_INTERVAL",
    "NOTICE_CANCELLED",
    "NOTICE_MAX_ITER",
    "NOTICE_STREAM_ERR",
    "NOTICE_UNKNOWN_TOOLS",
    "Agent",
    "ApprovalRequest",
    "Event",
    "Mode",
    "Phase",
    "ToolEvent",
    "Usage",
]
