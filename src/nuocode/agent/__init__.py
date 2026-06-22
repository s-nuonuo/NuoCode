"""Agent：ReAct 循环编排（chap04）+ 权限五层防御（chap06）+ 上下文管理（chap08）。

每一轮：上下文管理（layer1 落盘 + 必要时 layer2 摘要）→ 带工具定义发起请求 → 流式收集 →
若模型请求工具则执行并把结果回灌 → 进入下一轮；模型给出无工具调用纯文本即最终答复。

权限判定（chap06）：
- 工具执行前调用 ``engine.check`` 走前四层，必要时人在回路 Ask。

上下文管理（chap08）：
- 每轮请求前调 ``manage_context``：自动路径 + 落盘子系统。
- 流式响应若收到 ``PromptTooLongError``：紧急路径，``manage_context(EMERGENCY)`` 后
  在同一 ``run`` 内重试一次（仅一次）；二次仍 PTL → 抛错让上层处理。
- ``ReadFile`` 工具成功执行后把内容写进 ``recovery``（用于摘要恢复段）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from nuocode import llm, prompt
from nuocode.agent.runtime import SessionRuntime
from nuocode.compact import ManageInput, TriggerKind, manage_context
from nuocode.compact.token import estimate_tokens
from nuocode.compact.token import usage_anchor as _usage_anchor_sum
from nuocode.conversation import Conversation
from nuocode.llm import PromptTooLongError, Provider, ToolCall, ToolResult
from nuocode.permission import Engine, Mode, Outcome
from nuocode.prompt.skills_block import (
    ActiveSkillEntry,
    SkillCatalogItem,
    render_active_skills_block,
    render_skills_catalog,
)
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
NOTICE_PTL_RECOVERED = "（上下文超长，已紧急压缩并重试。）"
NOTICE_PTL_FATAL = "（上下文超长且紧急压缩仍失败，本轮已中断。）"


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
    """人在回路：等待用户三选一。"""

    name: str
    args: str
    reason: str
    respond: asyncio.Future[Outcome]


@dataclass
class CompactEvent:
    """compact 通知事件：layer2 实际触发后由 Agent 发出，TUI 渲染一行简报。"""

    trigger: str  # "auto" / "manual" / "emergency"
    before_tokens: int
    after_tokens: int


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
    compact: CompactEvent | None = None


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
    """持有 provider / registry / engine / runtime，执行 ReAct 循环。"""

    def __init__(
        self,
        provider: Provider,
        registry: Registry,
        version: str,
        engine: Engine,
        runtime: SessionRuntime | None = None,
        context_window: int = 200_000,
        memory_manager=None,
        instruction_text: str = "",
        memory_text: str = "",
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._version = version
        self._engine = engine
        if runtime is None:
            # 兼容老调用方：构造一个临时 runtime（不落到磁盘外，使用临时目录）
            import tempfile

            from nuocode.compact import new_session_context

            runtime = SessionRuntime(session=new_session_context(tempfile.gettempdir()))
        self._runtime = runtime
        self._context_window = context_window
        self._mem_mgr = memory_manager
        self._instruction_text = instruction_text
        self._memory_text = memory_text
        self._turn_count = 0
        # chap11：Skill catalog（可选）与全量工具注册表（fork 场景使用）
        self._catalog = None
        self._full_registry: Registry | None = None

    def with_catalog(self, catalog) -> Agent:  # noqa: ANN001
        """chap11：注入 Skill catalog。返回 self 以便链式调用。"""
        self._catalog = catalog
        return self

    def with_filtered_registry(self, full: Registry) -> Agent:
        """chap11：fork 子 Agent 场景使用：保留完整 registry 引用以便后续反向查找。"""
        self._full_registry = full
        return self

    def activate_skill(self, name: str, body: str) -> None:
        self._runtime.active_skills.activate(name, body)

    def clear_active_skills(self) -> None:
        self._runtime.active_skills.clear()

    @property
    def runtime(self) -> SessionRuntime:
        return self._runtime

    async def run(
        self,
        conv: Conversation,
        mode: Mode = Mode.DEFAULT,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        if cancel is None:
            cancel = asyncio.Event()

        async with self._runtime.run_lock:
            async for ev in self._run_inner(conv, mode, cancel):
                yield ev

    async def _run_inner(
        self,
        conv: Conversation,
        mode: Mode,
        cancel: asyncio.Event,
    ) -> AsyncIterator[Event]:
        env = prompt.gather_environment(self._version, self._provider.model)
        # chap11：skills_catalog 注入稳定 system prompt（需代码体中保持稳定缓存前缀）
        skills_catalog_text = ""
        if self._catalog is not None:
            items = [
                SkillCatalogItem(name=s.meta.name, description=s.meta.description)
                for s in self._catalog.list()
            ]
            skills_catalog_text = render_skills_catalog(items)
        sys_prompt = prompt.build_system_prompt(
            self._instruction_text, self._memory_text, skills_catalog_text
        )
        # chap11：active skills 注入动态 env（每轮重建）
        active_block = render_active_skills_block(
            [ActiveSkillEntry(name=e.name, body=e.body) for e in self._runtime.active_skills.snapshot()]
        )
        env_text = env.render()
        if active_block:
            env_text = env_text + "\n\n" + active_block

        if mode == Mode.PLAN:
            defs = self._registry.read_only_definitions()
        else:
            defs = self._registry.definitions()

        # 重置该 conv 的 unknown_run 计数（重新进入 run 视为新一段会话）
        self._unknown_run_state[id(conv)] = 0

        for it in range(1, MAX_ITERATIONS + 1):
            yield Event(iter=it)

            if cancel.is_set():
                self._finish_cancelled(conv)
                return

            # ── 上下文管理（AUTO 路径） ──
            try:
                async for ev in self._run_manage_context(conv, defs, TriggerKind.AUTO):
                    yield ev
            except Exception as e:  # noqa: BLE001
                logger.warning("auto manage_context failed: %s", e)

            reminder = ""
            if mode == Mode.PLAN:
                full = it == 1 or (it - 1) % PLAN_REMINDER_INTERVAL == 0
                reminder = prompt.plan_reminder(full)

            # 单轮 ReAct：若发出 done / 终止 notice，整个 run 结束
            terminated = False
            async for ev in self._drive_one_round(
                conv, mode, defs, sys_prompt, env_text, reminder, cancel, it
            ):
                yield ev
                if ev.done:
                    terminated = True
                if ev.notice in (
                    NOTICE_PTL_FATAL,
                    NOTICE_STREAM_ERR,
                    NOTICE_CANCELLED,
                    NOTICE_UNKNOWN_TOOLS,
                ):
                    terminated = True
            if terminated:
                return

            if cancel.is_set():
                self._finish_cancelled(conv)
                return

            if self._unknown_run_state.get(id(conv), 0) >= MAX_UNKNOWN_RUN:
                yield Event(notice=NOTICE_UNKNOWN_TOOLS)
                self._ensure_assistant_tail(conv, NOTICE_UNKNOWN_TOOLS)
                yield Event(done=True)
                return

        yield Event(notice=NOTICE_MAX_ITER)
        self._ensure_assistant_tail(conv, NOTICE_MAX_ITER)
        yield Event(done=True)

    # 简化：用一个轻量 dict 跟踪 unknown_run（多 conv 隔离）
    _unknown_run_state: dict[int, int] = {}

    async def _drive_one_round(
        self,
        conv: Conversation,
        mode: Mode,
        defs,
        sys_prompt: str,
        env_text: str,
        reminder: str,
        cancel: asyncio.Event,
        iter_no: int,
    ) -> AsyncIterator[Event]:
        """驱动单轮 ReAct：stream → 工具执行 → 必要时 PTL 紧急重试。"""

        # 第一次尝试
        text, calls, usage, err = "", [], None, None
        async for ev in self._stream_once_gen(conv, defs, sys_prompt, env_text, reminder, cancel):
            if ev.err is not None:
                err = ev.err
                break
            if ev.text:
                yield Event(text=ev.text)
                text += ev.text
            if ev.tool:
                pass  # 不会发生
            if isinstance(getattr(ev, "_calls", None), list):
                calls = ev._calls  # type: ignore[attr-defined]
            if ev.usage is not None:
                usage = ev.usage

        # 处理 PTL：紧急路径重试 1 次
        if isinstance(err, PromptTooLongError):
            try:
                async for ev in self._run_manage_context(conv, defs, TriggerKind.EMERGENCY):
                    yield ev
            except Exception as e:  # noqa: BLE001
                logger.warning("emergency compact failed: %s", e)
                yield Event(notice=NOTICE_PTL_FATAL, err=err)
                self._ensure_assistant_tail(conv, NOTICE_PTL_FATAL)
                return

            yield Event(notice=NOTICE_PTL_RECOVERED)
            text, calls, usage, err = "", [], None, None
            async for ev in self._stream_once_gen(
                conv, defs, sys_prompt, env_text, reminder, cancel
            ):
                if ev.err is not None:
                    err = ev.err
                    break
                if ev.text:
                    yield Event(text=ev.text)
                    text += ev.text
                if isinstance(getattr(ev, "_calls", None), list):
                    calls = ev._calls  # type: ignore[attr-defined]
                if ev.usage is not None:
                    usage = ev.usage

        if err is not None:
            yield Event(notice=NOTICE_STREAM_ERR, err=err)
            self._ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
            return

        if cancel.is_set():
            self._finish_cancelled(conv)
            yield Event(notice=NOTICE_CANCELLED)
            return

        if usage is not None:
            # 回写 anchor：以"主对话路径 stream 尾"为唯一锚点
            self._runtime.usage_anchor = _usage_anchor_sum(usage)
            self._runtime.anchor_msg_len = conv.length()
            yield Event(
                usage=Usage(
                    input=usage.input_tokens,
                    output=usage.output_tokens,
                    cache_write=usage.cache_write,
                    cache_read=usage.cache_read,
                )
            )

        if not calls:
            conv.add_assistant(_ensure_final(text))
            self._maybe_trigger_memory_update(conv)
            yield Event(done=True)
            return

        conv.add_assistant_with_tool_calls(text, calls)

        if self._all_unknown(calls):
            self._unknown_run_state[id(conv)] = self._unknown_run_state.get(id(conv), 0) + 1
        else:
            self._unknown_run_state[id(conv)] = 0

        results: list[ToolResult | None] = [None] * len(calls)
        completed = True
        try:
            async for ev in self._execute_batched(calls, mode, cancel, results):
                yield ev
        except asyncio.CancelledError:
            completed = False
            for k, c in enumerate(calls):
                if results[k] is None:
                    results[k] = ToolResult(
                        tool_call_id=c.id, content=NOTICE_CANCELLED, is_error=True
                    )
            real_results: list[ToolResult] = [r for r in results if r is not None]
            conv.add_tool_results(real_results)
            self._track_file_reads(calls, real_results)
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
        self._track_file_reads(calls, real_results)

        if not completed:
            self._ensure_assistant_tail(conv, NOTICE_CANCELLED)
            yield Event(notice=NOTICE_CANCELLED)
            return

    # ───────── 内部：stream + manage_context ─────────

    async def _stream_once_gen(
        self,
        conv: Conversation,
        defs,
        sys_prompt: str,
        env_text: str,
        reminder: str,
        cancel: asyncio.Event,
    ) -> AsyncIterator[Event]:
        """单轮 stream：把 Provider 事件翻译成本模块 Event；calls 通过 ``ev._calls`` 私有属性回传。"""

        req = llm.Request(
            messages=conv.messages(),
            tools=defs,
            system=llm.System(stable=sys_prompt, environment=env_text),
            reminder=reminder,
        )
        calls_buf: list[ToolCall] = []
        try:
            async for ev in self._provider.stream(req):
                if cancel.is_set():
                    return
                if ev.err is not None:
                    yield Event(err=ev.err)
                    return
                if ev.text:
                    yield Event(text=ev.text)
                if ev.tool_calls:
                    calls_buf.extend(ev.tool_calls)
                if ev.usage is not None:
                    out = Event(
                        usage=llm.Usage(
                            input_tokens=ev.usage.input_tokens,
                            output_tokens=ev.usage.output_tokens,
                            cache_write=ev.usage.cache_write,
                            cache_read=ev.usage.cache_read,
                        )
                    )
                    yield out
                if ev.done:
                    out = Event()
                    out._calls = list(calls_buf)  # type: ignore[attr-defined]
                    yield out
                    return
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            yield Event(err=e)

    async def _run_manage_context(
        self,
        conv: Conversation,
        defs,
        trigger: TriggerKind,
    ) -> AsyncIterator[Event]:
        """共享 compact 入口：把估算 → manage_context → CompactEvent 串起来。"""
        msgs = conv.messages()
        est = estimate_tokens(self._runtime.usage_anchor, msgs, self._runtime.anchor_msg_len)
        in_ = ManageInput(
            conv=conv,
            provider=self._provider,
            context_window=self._context_window,
            tool_defs=list(defs),
            replacement=self._runtime.replacement,
            recovery=self._runtime.recovery,
            auto_tracking=self._runtime.auto_tracking,
            session=self._runtime.session,
            usage_anchor=self._runtime.usage_anchor,
            anchor_msg_len=self._runtime.anchor_msg_len,
            estimated_token=est,
            trigger=trigger,
        )
        out = await manage_context(in_)
        # 仅在 layer2 真正发生时发 CompactEvent。
        # AUTO 分支即使只跑了 layer1，after_tokens 可能仍 < before_tokens；
        # 但 manage_context 现状下 AUTO 没触发 layer2 时 after_tokens = est_tokens（layer1 后估算），
        # before_tokens = 入口 estimated_token（layer1 前估算）。两者可能相等也可能不等。
        # 因此用一个保守判定：手动 / 紧急一律通知；自动仅在 message 数量真的减少时通知。
        layer2_happened = False
        if trigger == TriggerKind.MANUAL or trigger == TriggerKind.EMERGENCY:
            layer2_happened = True
        else:
            # AUTO：检查熔断 + 阈值；用 ``conv.length()`` 简化判断—
            # layer2 后必产出"摘要 + (assistant 桥) + 近期"少量条数。
            # 这里用 after_tokens 与 before_tokens 的相对差距 + 阈值判定即可。
            from nuocode.compact.const import AUTO_SAFETY_MARGIN, SUMMARY_RESERVE

            threshold = self._context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN
            layer2_happened = (
                out.before_tokens >= threshold
                and out.after_tokens < out.before_tokens
                and not self._runtime.auto_tracking.tripped()
            )

        if layer2_happened:
            yield Event(
                compact=CompactEvent(
                    trigger=trigger.value,
                    before_tokens=out.before_tokens,
                    after_tokens=out.after_tokens,
                )
            )
            self._runtime.usage_anchor = 0
            self._runtime.anchor_msg_len = conv.length()

    async def run_force_compact(self, conv: Conversation) -> AsyncIterator[Event]:
        """TUI ``/compact`` 入口：手动路径，与 ``run`` 互斥。"""
        async with self._runtime.run_lock:
            defs = self._registry.definitions()
            try:
                async for ev in self._run_manage_context(conv, defs, TriggerKind.MANUAL):
                    yield ev
            except Exception as e:  # noqa: BLE001
                yield Event(err=e, notice=NOTICE_STREAM_ERR)

    # ───────── 文件追踪 ─────────

    def _track_file_reads(self, calls: list[ToolCall], results: list[ToolResult]) -> None:
        """把 ``ReadFile`` 工具的成功结果写进 RecoveryState。

        约定：``ReadFile`` 工具入参 JSON 中带 ``path`` 字段；结果为带行号前缀的文本。
        本方法去掉行号前缀（``\\d+→`` 模式），仅存纯净内容。
        """
        import re

        prefix_re = re.compile(r"^\s*\d+→", re.MULTILINE)
        by_id = {c.id: c for c in calls}
        for r in results:
            if r.is_error:
                continue
            c = by_id.get(r.tool_call_id)
            if c is None or c.name != "ReadFile":
                continue
            try:
                args = json.loads(c.input or "{}")
            except json.JSONDecodeError:
                continue
            path = args.get("path")
            if not isinstance(path, str) or not path:
                continue
            try:
                abs_path = str(Path(path).resolve())
            except OSError:
                abs_path = path
            cleaned = prefix_re.sub("", r.content or "")
            self._runtime.recovery.record_file(abs_path, cleaned)

    # ───────── 工具批量执行（保持原实现） ─────────

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
                j = i
                while j < n and self._registry.is_read_only(calls[j].name):
                    j += 1

                previews = [_preview_args(calls[k].input) for k in range(i, j)]
                decisions: list[tuple[Decision, str]] = []
                for k in range(i, j):
                    decisions.append(self._engine.check(mode, calls[k], True))

                for k in range(i, j):
                    yield Event(
                        tool=ToolEvent(
                            name=calls[k].name,
                            args=previews[k - i],
                            phase=Phase.START,
                        )
                    )

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

    def _maybe_trigger_memory_update(self, conv: Conversation) -> None:
        """Done 分支末尾：每 5 轮或显式记忆请求触发异步记忆更新。"""
        if self._mem_mgr is None:
            return
        self._turn_count += 1
        recent = self._extract_recent_turn(conv)
        try:
            from nuocode.memory import Manager as _MemMgr  # noqa: N814
        except Exception:  # noqa: BLE001
            return
        has_signal = _MemMgr.has_memory_signal(recent)
        if not (self._turn_count % 5 == 0 or has_signal):
            return
        try:
            asyncio.create_task(self._mem_mgr.update_async(recent))
        except RuntimeError:
            # 无运行中的 event loop（极少触发）
            logger.debug("无 event loop，跳过记忆更新")

    def _extract_recent_turn(self, conv: Conversation) -> list:
        """从最后一条 user 消息到结尾。"""
        msgs = conv.messages()
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].role == llm.ROLE_USER:
                return msgs[i:]
        return msgs[-2:] if len(msgs) >= 2 else msgs


__all__ = [
    "MAX_ITERATIONS",
    "MAX_UNKNOWN_RUN",
    "PLAN_REMINDER_INTERVAL",
    "NOTICE_CANCELLED",
    "NOTICE_MAX_ITER",
    "NOTICE_PTL_FATAL",
    "NOTICE_PTL_RECOVERED",
    "NOTICE_STREAM_ERR",
    "NOTICE_UNKNOWN_TOOLS",
    "Agent",
    "ApprovalRequest",
    "CompactEvent",
    "Event",
    "Mode",
    "Phase",
    "SessionRuntime",
    "ToolEvent",
    "Usage",
]
